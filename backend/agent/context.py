from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, PlanStep, ReflectionResult, StepResult, UserProfile
from backend.llm.client import chat_completion_text
from backend.core.logging_utils import get_logger

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
logger = get_logger(__name__)


class ContextManager:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()
        self._project_root = Path(__file__).resolve().parents[2]

    def _merge_items_by_knowledge_point(self, old: Any, new: Any) -> Any:
        """Merge tool outputs that follow the `{items|sections:[{knowledge_point:...}, ...]}` convention.

        Notes:
        - When the same knowledge point is produced multiple times (e.g. multi-pass web search),
          we try to *accumulate* common list fields (results/pages/examples/exercises) instead of
          overwriting the entire item.
        - For tools that only output scalar fields, "new wins" still applies.
        """

        if not isinstance(new, dict):
            return new
        if not isinstance(old, dict):
            old = {}

        def _extract_entries(blob: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
            if isinstance(blob.get("items"), list):
                return "items", [x for x in (blob.get("items") or []) if isinstance(x, dict)]
            if isinstance(blob.get("sections"), list):
                return "sections", [x for x in (blob.get("sections") or []) if isinstance(x, dict)]
            kp = str(blob.get("knowledge_point") or "").strip()
            if kp:
                # Single-entry style payload. Default to the "items" convention.
                return "items", [blob]
            return "", []

        old_key, old_entries = _extract_entries(old)
        new_key, new_entries = _extract_entries(new)
        if not new_entries:
            return new

        # Mixing conventions within the same key usually means caller misuse; prefer "new wins".
        if old_key and new_key and old_key != new_key:
            return new

        list_key = new_key or old_key or "items"

        def _dedup_list(items: List[Any]) -> List[Any]:
            out: List[Any] = []
            seen: set[str] = set()
            for it in items or []:
                key = ""
                if isinstance(it, str):
                    key = it.strip()
                elif isinstance(it, dict):
                    for k in ("url", "question_id", "questionId", "id", "title"):
                        v = it.get(k)
                        if isinstance(v, str) and v.strip():
                            key = f"{k}:{v.strip()}"
                            break
                if not key:
                    try:
                        key = json.dumps(it, ensure_ascii=False, sort_keys=True)
                    except Exception:
                        key = str(it)
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
            return out

        def _merge_kp_item(prev: Dict[str, Any], nxt: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(prev)
            for k, v in nxt.items():
                # Tools differ in naming; support both the search-style keys and study-materials keys.
                if k in {"results", "pages", "web_results", "web_pages", "examples", "exercises"} and isinstance(
                    v, list
                ):
                    prev_list = out.get(k) if isinstance(out.get(k), list) else []
                    merged_list = _dedup_list([*prev_list, *v])
                    cap = {
                        "results": 40,
                        "pages": 8,
                        "web_results": 20,
                        "web_pages": 6,
                        "examples": 8,
                        "exercises": 20,
                    }.get(k, 40)
                    out[k] = merged_list[:cap]
                    continue

                if k in {"queries", "query_variants"} and isinstance(v, list):
                    prev_list = out.get(k) if isinstance(out.get(k), list) else []
                    out[k] = _dedup_list([*prev_list, *v])[:40]
                    continue

                # Merge multi-pass "summary" notes (common for web_search_knowledge in deep/research mode).
                if k == "summary" and isinstance(v, str):
                    new_s = v.strip()
                    if not new_s:
                        continue
                    prev_s = out.get("summary")
                    prev_s = prev_s.strip() if isinstance(prev_s, str) else ""
                    if not prev_s:
                        out["summary"] = new_s
                        continue
                    if new_s in prev_s:
                        continue
                    if prev_s in new_s:
                        out["summary"] = new_s
                        continue
                    combined = prev_s.rstrip() + "\n\n---\n\n" + new_s.lstrip()
                    # Keep bounded so the context won't explode.
                    if len(combined) > 9000:
                        combined = combined[:8999].rstrip() + "…"
                    out["summary"] = combined
                    continue

                # Prefer newer meaningful values; ignore empty placeholders.
                if v in (None, "", [], {}):
                    continue
                out[k] = v

            kp = str(nxt.get("knowledge_point") or prev.get("knowledge_point") or "").strip()
            if kp:
                out["knowledge_point"] = kp
            return out

        merged: Dict[str, Dict[str, Any]] = {}
        order: List[str] = []

        for it in old_entries:
            kp = str(it.get("knowledge_point") or "").strip()
            if not kp:
                continue
            merged[kp] = it
            if kp not in order:
                order.append(kp)

        for it in new_entries:
            kp = str(it.get("knowledge_point") or "").strip()
            if not kp:
                continue
            if kp not in order:
                order.append(kp)
            if kp in merged and isinstance(merged.get(kp), dict) and isinstance(it, dict):
                merged[kp] = _merge_kp_item(merged[kp], it)
            else:
                merged[kp] = it

        out: Dict[str, Any] = dict(old)
        # Prefer newer top-level metadata (difficulty/subject/etc.), but always rebuild list entries.
        for k, v in new.items():
            if k == list_key:
                continue
            out[k] = v
        out[list_key] = [merged[kp] for kp in order if kp in merged]
        return out

    def create_context(
        self, *, user_profile: UserProfile, system_instructions: str, current_task: str
    ) -> CompressedContext:
        return CompressedContext(
            user_profile=user_profile,
            system_instructions=system_instructions,
            current_task=current_task,
        )

    def append_message(self, ctx: CompressedContext, *, role: str, content: str) -> None:
        ctx.recent_messages.append({"role": role, "content": content})

    async def on_step_result(self, ctx: CompressedContext, *, step: PlanStep, result: StepResult) -> None:
        _ = step
        async with ctx.working_memory_lock:
            ctx.working_memory.setdefault("step_results", []).append(
                {"step_id": result.step_id, "tool": result.tool, "success": result.success, "error": result.error}
            )
            # Persist the latest tool outputs for downstream steps.
            if result.success:
                if result.tool in {
                    "web_search_knowledge",
                    "browse_web_pages",
                    "wikipedia_search",
                    "mediawiki_search",
                    "github_search",
                    "stackexchange_search",
                    "search_questions_by_knowledge",
                    "aggregate_knowledge",
                    "synthesize_sources",
                    "detect_knowledge_type",
                    "generate_outline",
                    # Study-materials generation runs per knowledge point; merge to avoid parallel subagents clobbering.
                    "generate_study_material",
                    "critique_draft",
                    "refine_draft",
                    "generate_diagrams",
                }:
                    prev = ctx.working_memory.get(result.tool)
                    merged = self._merge_items_by_knowledge_point(prev, result.output)
                    ctx.working_memory[result.tool] = merged
                    if result.tool == "generate_study_material":
                        # Back-compat alias used by some callers.
                        ctx.working_memory["study_material"] = merged
                else:
                    ctx.working_memory[result.tool] = result.output

    async def on_reflection(self, ctx: CompressedContext, reflection: ReflectionResult) -> None:
        async with ctx.working_memory_lock:
            ctx.working_memory["last_reflection"] = {
                "passed": reflection.passed,
                "issues": reflection.issues,
                "suggestions": reflection.suggestions,
            }

    async def compress_if_needed(self, ctx: CompressedContext) -> None:
        # Always enforce sliding window first (Level 1 -> Level 2).
        if len(ctx.recent_messages) > self.config.sliding_window_size:
            await self._compress_level2(ctx)

        token_est = self.estimate_tokens(ctx)
        if token_est < self.config.token_threshold:
            return

        # Soft compaction (Level 2).
        if token_est < self.config.emergency_token_threshold:
            await self._compress_level2(ctx)
            token_est = self.estimate_tokens(ctx)
            if token_est < self.config.token_threshold:
                return

        # Hard compaction (Level 3 checkpoint).
        await self._save_checkpoint(ctx)

    def estimate_tokens(self, ctx: CompressedContext) -> int:
        total = 0
        total += self._estimate_tokens_for_text(ctx.system_instructions or "")
        total += self._estimate_tokens_for_text(ctx.current_task or "")
        total += self._estimate_tokens_for_text(ctx.checkpoint_summary or "")
        for m in ctx.compressed_history:
            total += self._estimate_tokens_for_text(str(m.get("content") or ""))
        for m in ctx.recent_messages:
            total += self._estimate_tokens_for_text(str(m.get("content") or ""))
        # Small overhead for roles/JSON framing.
        total += 50
        return max(1, total)

    def _estimate_tokens_for_text(self, text: str) -> int:
        raw = text or ""
        if not raw:
            return 0
        cjk = len(_CJK_RE.findall(raw))
        other = max(0, len(raw) - cjk)
        # Heuristic: CJK ~ 1.5 chars/token; other ~ 4 chars/token.
        return int(cjk / 1.5 + other / 4) + 1

    async def _compress_level2(self, ctx: CompressedContext) -> None:
        """Summarize oldest recent messages into a compact summary block."""
        keep_n = max(1, int(self.config.sliding_window_size))
        if len(ctx.recent_messages) <= keep_n:
            return

        to_summarize = ctx.recent_messages[:-keep_n]
        ctx.recent_messages = ctx.recent_messages[-keep_n:]

        summary = await self._summarize_messages(to_summarize)
        if summary:
            ctx.compressed_history.append(
                {
                    "role": "summary",
                    "content": summary,
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

        if len(ctx.compressed_history) > self.config.compressed_history_max:
            await self._save_checkpoint(ctx)

    async def _save_checkpoint(self, ctx: CompressedContext) -> str:
        """Persist full context to disk; keep only a checkpoint summary in active context."""
        checkpoint_dir = self._project_root / self.config.checkpoint_dir
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        fname = f"checkpoint-{ts}-{uuid.uuid4().hex[:8]}.json"
        path = checkpoint_dir / fname

        payload = json.loads(ctx.to_json())
        payload["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        payload["token_estimate"] = self.estimate_tokens(ctx)
        await asyncio.to_thread(
            path.write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Create/refresh checkpoint summary from all compressed blocks + recent window.
        blocks: List[Dict[str, Any]] = []
        blocks.extend(ctx.compressed_history)
        blocks.extend(ctx.recent_messages)
        summary = await self._summarize_messages(blocks, target_chars=500)

        ctx.checkpoint_file = str(path)
        ctx.checkpoint_summary = summary or ctx.checkpoint_summary or ""
        ctx.compressed_history = []

        return str(path)

    async def _summarize_messages(self, messages: List[Dict[str, Any]], *, target_chars: int = 220) -> str:
        """Summarize messages into a compact, tool-aware memory block."""
        if not messages:
            return ""

        prompt = f"""Compress the conversation/log below into one concise summary of about {target_chars} characters. Preserve:\n- The user's main goals and constraints.\n- Key decisions from Plan/Act/Reflect.\n- Important tool-call results or errors.\n\nOutput a plain-text summary only, not Markdown. Match the dominant conversation language.\n\nLog:\n{json.dumps(messages, ensure_ascii=False)}\n"""
        normalized_model = str(self.config.summarizer_model or "").strip()
        if normalized_model:
            try:
                text = await chat_completion_text(
                    messages=[
                        {"role": "system", "content": "You are a context compressor. Output a plain-text summary only."},
                        {"role": "user", "content": prompt},
                    ],
                    model=normalized_model,
                    temperature=0.2,
                    max_tokens=400,
                    retries=3,
                    req_id_prefix="ctx-sum",
                )
                text = str(text or "").strip()
                if text:
                    return text
            except Exception:
                logger.debug("context_compact_text_extract_failed", exc_info=True)

        # Final fallback: never raise; produce a compact local summary.
        parts = []
        for m in messages[-6:]:
            role = str(m.get("role") or "unknown")
            content = str(m.get("content") or "")[:120]
            if content:
                parts.append(f"{role}: {content}")
        joined = " | ".join(parts)
        return joined[:target_chars]
