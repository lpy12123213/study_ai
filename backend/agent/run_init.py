from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from backend.agent.config import AgentConfig
from backend.agent.context import ContextManager
from backend.agent.policy import StudyMaterialsPolicy
from backend.agent.types import AgentState, CompressedContext, UserProfile, agent_event
from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


async def initialize_run(
    *,
    user_input: str,
    user_id: str,
    preferences: Optional[Dict[str, Any]],
    options: Optional[Dict[str, Any]],
    resume_working_memory: Optional[Dict[str, Any]],
    iteration_offset: int,
    max_iterations: Optional[int],
    out: Dict[str, Any],
    config: AgentConfig,
    memory_store: Any,
    semantic_store: Any,
    context_manager: ContextManager,
    system_instructions: str,
    set_state: Any,
) -> AsyncIterator[Dict[str, Any]]:
    """Initialize an AgentCore run.

    This function yields AgentEvents and populates `out` with:
    - profile: UserProfile
    - ctx: CompressedContext
    - policy: StudyMaterialsPolicy
    - iter_offset: int
    - budget: int
    - export_only: bool
    - skip_export: bool
    """

    yield agent_event("status", {"content": "初始化上下文…"})
    try:
        set_state(AgentState.WAITING_TOOL)
    except Exception:
        logger.warning("agent_set_state_failed", extra={"next_state": str(AgentState.WAITING_TOOL)}, exc_info=True)

    profile_step_id = f"get_user_profile-{uuid.uuid4().hex[:8]}"
    yield agent_event(
        "tool_call",
        {"step_id": profile_step_id, "name": "get_user_profile", "title": "读取用户画像", "arguments": {"user_id": user_id}},
    )
    try:
        profile: UserProfile = await memory_store.get_user_profile(user_id=user_id)
        yield agent_event(
            "tool_result",
            {
                "step_id": profile_step_id,
                "name": "get_user_profile",
                "title": "读取用户画像",
                "success": True,
                "output": {
                    "user_id": profile.user_id,
                    "ability_level": profile.ability_level,
                    "ability_score": profile.ability_score,
                    "preferences": dict(profile.preferences or {}),
                },
            },
        )
    except Exception as exc:
        logger.warning("agent_profile_fetch_failed; using_default_profile", extra={"user_id": user_id}, exc_info=True)
        yield agent_event(
            "tool_result",
            {
                "step_id": profile_step_id,
                "name": "get_user_profile",
                "title": "读取用户画像",
                "success": False,
                "error": str(exc),
            },
        )
        profile = UserProfile(user_id=str(user_id or "anonymous").strip() or "anonymous")
        yield agent_event("status", {"content": "读取用户画像失败，已使用默认用户画像继续运行。"})

    pref_patch: Dict[str, Any] = {}
    if isinstance(preferences, dict):
        for k, v in preferences.items():
            key = str(k or "").strip()
            if not key:
                continue
            if v in (None, "", [], {}):
                continue
            pref_patch[key] = v
    if pref_patch:
        try:
            profile = await memory_store.update_user_profile(user_id=user_id, patch=pref_patch)
        except Exception:
            try:
                prefs = dict(profile.preferences or {})
                prefs.update(pref_patch)
                profile.preferences = prefs
            except Exception:
                logger.debug("agent_profile_preference_fallback_failed", exc_info=True)

    ctx: CompressedContext = context_manager.create_context(
        user_profile=profile,
        system_instructions=system_instructions,
        current_task=user_input,
    )

    study_opts = dict(options) if isinstance(options, dict) else {}
    if "strict_llm" not in study_opts:
        raw = str(os.getenv("STUDY_MATERIALS_STRICT_LLM") or "1").strip().lower()
        study_opts["strict_llm"] = raw in {"1", "true", "yes", "y", "on"}

    if isinstance(resume_working_memory, dict) and resume_working_memory:
        for k, v in resume_working_memory.items():
            key = str(k or "").strip()
            if not key:
                continue
            if key in {"study_options", "_abort_execution", "_fatal_error", "_export_subagent_kp"}:
                continue
            ctx.working_memory[key] = v
        ctx.working_memory.pop("_abort_execution", None)
        ctx.working_memory.pop("_fatal_error", None)
        ctx.working_memory.pop("_export_subagent_kp", None)

    ctx.working_memory["study_options"] = study_opts

    # Cross-task semantic memory: retrieve related historical snippets (best-effort).
    try:
        subject_pref = str(ctx.user_profile.preferences.get("subject") or "").strip()
        query = " ".join([x for x in [subject_pref, user_input] if str(x or "").strip()]).strip()
        if query:
            semantic_timeout_s = float(os.getenv("AGENT_SEMANTIC_SEARCH_TIMEOUT_S") or "1.2")
            semantic_timeout_s = max(0.2, min(semantic_timeout_s, 10.0))
            matches = await asyncio.wait_for(
                semantic_store.search(user_id=user_id, subject=subject_pref, query=query, limit=5),
                timeout=semantic_timeout_s,
            )
            if matches:
                ctx.working_memory["semantic_memory"] = matches
    except Exception:
        logger.debug("semantic_store_search_failed", exc_info=True)

    context_manager.append_message(ctx, role="user", content=user_input)

    policy = StudyMaterialsPolicy()
    try:
        iter_offset = int(iteration_offset or 0)
    except Exception:
        iter_offset = 0
    iter_offset = max(0, iter_offset)

    if max_iterations is not None:
        try:
            budget = int(max_iterations)
        except Exception:
            budget = 0
        budget = max(1, budget)
    else:
        budget = int(policy.iteration_budget(ctx, default_cap=int(config.max_iterations or 1)) or 1)
        budget = max(1, budget)

    try:
        opts_for_mode = ctx.working_memory.get("study_options")
        opts_for_mode = dict(opts_for_mode) if isinstance(opts_for_mode, dict) else {}
    except Exception:
        opts_for_mode = {}
    continue_mode = str(opts_for_mode.get("continue_mode") or "").strip().lower()

    out["profile"] = profile
    out["ctx"] = ctx
    out["policy"] = policy
    out["iter_offset"] = iter_offset
    out["budget"] = budget
    out["export_only"] = continue_mode == "fix_export"
    out["skip_export"] = continue_mode == "skip_export"
