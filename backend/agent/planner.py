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
                id=sid("split_knowledge_points"),
                title="拆分知识点",
                tool="split_knowledge_points",
                arguments={"topic": topic, "subject": subject, "min_points": 3, "max_points": 8},
            ),
            PlanStep(
                id=sid("web_search_knowledge"),
                title="联网搜索知识点（Exa 优先，智谱兜底）",
                tool="web_search_knowledge",
                arguments={"topic": topic, "subject": subject, "limit": 5, "concurrency": 3},
            ),
            PlanStep(
                id=sid("wikipedia_search"),
                title="Wikipedia 百科检索",
                tool="wikipedia_search",
                arguments={"topic": topic, "subject": subject, "lang": "zh", "sentences": 4, "concurrency": 3},
            ),
            PlanStep(
                id=sid("search_questions_by_knowledge"),
                title="题库按知识点检索（例题+练习题）",
                tool="search_questions_by_knowledge",
                arguments={
                    "topic": topic,
                    "subject": subject,
                    "difficulty": difficulty,
                    "examples_limit": 1,
                    "exercises_limit": 4,
                    "max_pages": 2,
                },
            ),
            PlanStep(
                id=sid("aggregate_knowledge"),
                title="聚合多源资料",
                tool="aggregate_knowledge",
                arguments={"topic": topic, "subject": subject},
            ),
            PlanStep(
                id=sid("generate_study_material"),
                title="生成讲解与例题解答",
                tool="generate_study_material",
                arguments={"topic": topic, "subject": subject, "max_examples": 1, "max_points": 8},
            ),
            PlanStep(
                id=sid("assemble_study_archive"),
                title="组装自学档案 Markdown",
                tool="assemble_study_archive",
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
                id=sid("save_markdown_file"),
                title="保存 Markdown 到文件",
                tool="save_markdown_file",
                arguments={"topic": topic, "dir": "study_archives"},
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
            f"计划：拆分→百科/联网→题库→聚合→生成→组装→保存→审查（学科：{subject}，难度：{difficulty}）"
        )
        return ExecutionPlan(topic=topic, steps=steps, rationale=rationale)

