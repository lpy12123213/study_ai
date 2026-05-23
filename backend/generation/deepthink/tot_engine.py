from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Sequence

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


@dataclass
class ThoughtNode:
    id: str
    parent_id: Optional[str]
    depth: int
    thought: str
    reasoning: str
    score: Optional[float] = None
    eval_reasoning: Optional[str] = None
    issues: List[str] = field(default_factory=list)
    status: str = "pending"  # pending | evaluated | selected | pruned | final
    is_final: bool = False
    children: List[str] = field(default_factory=list)


ProposeFn = Callable[[str, str, Sequence[ThoughtNode], int], Awaitable[List[Dict[str, Any]]]]
EvaluateFn = Callable[[str, str, Sequence[ThoughtNode], Dict[str, Any]], Awaitable[Dict[str, Any]]]


class ToTEngine:
    """
    Tree-of-Thoughts engine using Beam Search.

    The engine is model-agnostic; it receives two async callables:
    - propose_fn: generate N candidate next steps from the current path
    - evaluate_fn: score each candidate step (0-10) and return reasoning/issues
    """

    def __init__(
        self,
        *,
        question: str,
        subject: str,
        branch_factor: int,
        beam_width: int,
        max_depth: int,
        prune_threshold: float,
        timeout_seconds: int,
        propose_fn: ProposeFn,
        evaluate_fn: EvaluateFn,
    ) -> None:
        self.question = (question or "").strip()
        self.subject = (subject or "").strip() or "高中数学"
        self.branch_factor = max(1, int(branch_factor))
        self.beam_width = max(1, int(beam_width))
        self.max_depth = max(1, int(max_depth))
        self.prune_threshold = float(prune_threshold)
        self.timeout_seconds = max(1, int(timeout_seconds))
        self._propose_fn = propose_fn
        self._evaluate_fn = evaluate_fn

        self.nodes: Dict[str, ThoughtNode] = {}
        self.best_leaf_id: str = "root"
        self.started_at = 0.0

    def _new_id(self) -> str:
        return uuid.uuid4().hex

    def _path_to(self, node_id: str) -> List[ThoughtNode]:
        path: List[ThoughtNode] = []
        cur = self.nodes.get(node_id)
        while cur is not None:
            path.append(cur)
            if not cur.parent_id:
                break
            cur = self.nodes.get(cur.parent_id)
        return list(reversed(path))

    def _pick_best_leaf(self, candidates: List[ThoughtNode]) -> ThoughtNode:
        if not candidates:
            return self.nodes.get(self.best_leaf_id) or self.nodes["root"]

        def key(n: ThoughtNode) -> tuple:
            return (1 if n.is_final else 0, float(n.score or 0.0), n.depth)

        return max(candidates, key=key)

    async def search(self) -> AsyncIterator[Dict[str, Any]]:
        self.started_at = time.monotonic()

        root = ThoughtNode(
            id="root",
            parent_id=None,
            depth=0,
            thought="题目分析（根节点）",
            reasoning="",
            score=None,
            eval_reasoning=None,
            status="selected",
            is_final=False,
        )
        self.nodes[root.id] = root

        yield {
            "type": "node_generated",
            "node": {
                "id": root.id,
                "parentId": None,
                "depth": root.depth,
                "thought": root.thought,
                "reasoning": root.reasoning,
                "status": root.status,
                "isFinal": root.is_final,
            },
        }

        frontier: List[ThoughtNode] = [root]
        best_so_far: ThoughtNode = root

        for layer in range(1, self.max_depth + 1):
            if time.monotonic() - self.started_at > self.timeout_seconds:
                break

            # 1) Generate
            children: List[ThoughtNode] = []
            async def _propose_one(parent: ThoughtNode) -> tuple[ThoughtNode, List[Dict[str, Any]]]:
                path = self._path_to(parent.id)
                try:
                    proposals = await self._propose_fn(self.question, self.subject, path, self.branch_factor)
                except Exception:
                    logger.exception("tot_propose_failed", extra={"parent_id": parent.id})
                    proposals = []
                if not isinstance(proposals, list):
                    proposals = []
                return parent, proposals

            propose_tasks = [asyncio.create_task(_propose_one(parent)) for parent in frontier]
            for fut in asyncio.as_completed(propose_tasks):
                parent, proposals = await fut

                for p in proposals[: self.branch_factor]:
                    thought = str((p or {}).get("thought") or "").strip()
                    if not thought:
                        continue
                    reasoning = str((p or {}).get("reasoning") or "").strip()
                    is_final = bool((p or {}).get("is_final") or (p or {}).get("isFinal") or False)
                    node = ThoughtNode(
                        id=self._new_id(),
                        parent_id=parent.id,
                        depth=parent.depth + 1,
                        thought=thought,
                        reasoning=reasoning,
                        status="pending",
                        is_final=is_final,
                    )
                    self.nodes[node.id] = node
                    parent.children.append(node.id)
                    children.append(node)
                    yield {
                        "type": "node_generated",
                        "node": {
                            "id": node.id,
                            "parentId": node.parent_id,
                            "depth": node.depth,
                            "thought": node.thought,
                            "reasoning": node.reasoning,
                            "status": node.status,
                            "isFinal": node.is_final,
                        },
                    }

            if not children:
                break

            # 2) Evaluate concurrently
            async def _eval_one(node: ThoughtNode) -> ThoughtNode:
                parent_path = self._path_to(node.parent_id or "root")
                payload = {"thought": node.thought, "reasoning": node.reasoning, "is_final": node.is_final}
                try:
                    res = await self._evaluate_fn(self.question, self.subject, parent_path, payload)
                except Exception:
                    logger.exception("tot_evaluate_failed", extra={"node_id": node.id})
                    res = {}
                score = res.get("score")
                try:
                    node.score = float(score)
                except (TypeError, ValueError):
                    node.score = 0.0
                node.eval_reasoning = str(res.get("reasoning") or "").strip() or None
                issues = res.get("issues")
                if isinstance(issues, list):
                    node.issues = [str(x) for x in issues if str(x).strip()][:10]
                node.status = "evaluated"
                return node

            tasks = [asyncio.create_task(_eval_one(n)) for n in children]
            for fut in asyncio.as_completed(tasks):
                n = await fut
                yield {
                    "type": "node_evaluated",
                    "nodeId": n.id,
                    "score": float(n.score or 0.0),
                    "evalReasoning": n.eval_reasoning or "",
                    "issues": n.issues,
                    "status": n.status,
                }

            # 3) Prune + select
            viable: List[ThoughtNode] = []
            pruned: List[ThoughtNode] = []
            for n in children:
                if float(n.score or 0.0) < self.prune_threshold:
                    n.status = "pruned"
                    pruned.append(n)
                else:
                    viable.append(n)

            for n in pruned:
                yield {
                    "type": "node_pruned",
                    "nodeId": n.id,
                    "score": float(n.score or 0.0),
                    "reason": (n.eval_reasoning or (n.issues[0] if n.issues else "") or "").strip(),
                }

            if not viable:
                break

            finals = [n for n in viable if n.is_final]
            if finals:
                best_final = self._pick_best_leaf(finals)
                best_final.status = "final"
                best_so_far = best_final
                self.best_leaf_id = best_final.id
                yield {"type": "search_complete", "nodeId": best_final.id, "depth": best_final.depth}
                break

            frontier = sorted(viable, key=lambda n: float(n.score or 0.0), reverse=True)[: self.beam_width]
            for n in frontier:
                n.status = "selected"
                yield {"type": "node_selected", "nodeId": n.id}

            best_layer = self._pick_best_leaf(frontier)
            if float(best_layer.score or 0.0) >= float(best_so_far.score or 0.0):
                best_so_far = best_layer
                self.best_leaf_id = best_layer.id

            yield {
                "type": "depth_complete",
                "depth": layer,
                "frontierSize": len(frontier),
                "totalNodes": len(self.nodes),
            }

        best_leaf = self.nodes.get(self.best_leaf_id) or best_so_far
        path = self._path_to(best_leaf.id)
        yield {
            "type": "best_path",
            "path": [
                {
                    "nodeId": n.id,
                    "depth": n.depth,
                    "thought": n.thought,
                    "reasoning": n.reasoning,
                    "score": n.score,
                }
                for n in path
            ],
            "bestLeafId": best_leaf.id,
            "bestScore": float(best_leaf.score or 0.0),
            "elapsed": round(time.monotonic() - self.started_at, 3),
        }
