from __future__ import annotations

import uuid
from typing import Optional

from backend.agent.config import AgentConfig
from backend.agent.types import CompressedContext, ExecutionPlan, PlanStep, UserProfile
from backend.core.settings import DEFAULT_SUBJECT


class Planner:
    def __init__(self, *, config: Optional[AgentConfig] = None) -> None:
        self.config = config or AgentConfig.from_env()

    async def plan(
        self,
        *,
        topic: str,
        user_profile: UserProfile,
        context: CompressedContext,
        iteration: int = 0,
    ) -> ExecutionPlan:
        topic = (topic or "").strip()
        subject = str(user_profile.preferences.get("subject") or DEFAULT_SUBJECT).strip() or DEFAULT_SUBJECT

        # Simple difficulty heuristic (can be improved with more signals).
        score = float(user_profile.ability_score or 0.5)
        if score < 0.4:
            difficulty = "简单"
        elif score < 0.7:
            difficulty = "中等"
        else:
            difficulty = "困难"

        # If previous reflection exists, feed it into the next plan as a revision hint.
        last_reflection = context.working_memory.get("last_reflection") or {}
        issues = last_reflection.get("issues") if isinstance(last_reflection, dict) else None

        def sid(prefix: str) -> str:
            return f"{prefix}-{iteration}-{uuid.uuid4().hex[:8]}"

        steps = [
            PlanStep(
                id=sid("retrieve_knowledge"),
                title="检索知识点要点",
                tool="retrieve_knowledge",
                arguments={"topic": topic, "subject": subject, "difficulty": difficulty},
            ),
            PlanStep(
                id=sid("search_examples"),
                title="检索例题",
                tool="search_examples",
                arguments={"topic": topic, "subject": subject, "difficulty": difficulty, "limit": 3},
            ),
            PlanStep(
                id=sid("search_exercises"),
                title="检索练习题",
                tool="search_exercises",
                arguments={"topic": topic, "subject": subject, "difficulty": difficulty, "limit": 10},
            ),
            PlanStep(
                id=sid("analyze_topic"),
                title="分析知识点结构与讲解顺序",
                tool="analyze_topic",
                arguments={"topic": topic, "subject": subject},
            ),
            PlanStep(
                id=sid("generate_explanation"),
                title="生成知识点讲解",
                tool="generate_explanation",
                arguments={"topic": topic, "subject": subject},
            ),
            PlanStep(
                id=sid("generate_solutions"),
                title="为例题生成分步解答",
                tool="generate_solutions",
                arguments={"max_examples": 3},
            ),
            PlanStep(
                id=sid("assemble_markdown"),
                title="组装最终 Markdown",
                tool="assemble_markdown",
                arguments={"topic": topic, "subject": subject},
            ),
        ]

        if iteration > 0 and issues:
            steps.append(
                PlanStep(
                    id=sid("revise_markdown"),
                    title="根据审查问题修订 Markdown",
                    tool="revise_markdown",
                    arguments={"issues": issues},
                )
            )

        steps.append(
            PlanStep(
                id=sid("review_content"),
                title="内容审查",
                tool="review_content",
                arguments={"topic": topic, "subject": subject},
            )
        )

        rationale = (
            f"计划：检索→分析→生成→组装→审查（学科：{subject}，难度：{difficulty}，例题≈3，练习≈10）"
        )
        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

