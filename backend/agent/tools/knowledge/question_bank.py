from __future__ import annotations

from typing import Any, Dict, List

from backend.agent.types import CompressedContext
from backend.core.logging_utils import get_logger
from backend.crawler.manager import get_crawler
from backend.llm.client import is_llm_configured

logger = get_logger(__name__)


class QuestionBankToolsMixin:
    async def _tool_search_questions_by_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        """题库检索：按拆分后的知识点批量搜索例题与练习题。"""

        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip() or "中等"
        examples_limit = int(args.get("examples_limit") or 1)
        exercises_limit = int(args.get("exercises_limit") or 4)
        examples_limit = max(0, min(examples_limit, 3))
        exercises_limit = max(0, min(exercises_limit, 10))
        max_pages = int(args.get("max_pages") or 2)
        max_pages = max(1, min(max_pages, 3))

        points: List[str] = []
        provided = args.get("knowledge_points")
        if isinstance(provided, list):
            points = [str(x or "").strip() for x in provided if str(x or "").strip()]
        if not points:
            split_res = ctx.working_memory.get("split_knowledge_points")
            if isinstance(split_res, dict):
                kp = split_res.get("knowledge_points")
                if isinstance(kp, list):
                    points = [str(x or "").strip() for x in kp if str(x or "").strip()]
        if not points and topic:
            points = [topic]
        points = points[:15]

        crawler = await get_crawler(subject=subject)
        applied_subject = subject or getattr(crawler, "subject", "")

        items: List[Dict[str, Any]] = []
        for point in points:
            fetch_limit = int(args.get("limit") or 0) or max(18, (examples_limit + exercises_limit) * 4)
            fetch_limit = max(10, min(fetch_limit, 60))
            try:
                res = await crawler.search_by_knowledge(
                    knowledge_point=point,
                    subject=applied_subject,
                    limit=fetch_limit,
                    difficulty=difficulty,
                    max_pages=max_pages,
                    dedup_by_stem=True,
                    min_quality_score=10,
                    with_quality=True,
                    strict_subject=True,
                    require_difficulty=True,
                )
                questions = list(res.get("questions") or []) if isinstance(res, dict) else []
                examples = self._pick_questions(questions, limit=max(1, examples_limit)) if examples_limit else []
                used_ids = {str(q.get("question_id") or "").strip() for q in examples if isinstance(q, dict)}
                remaining = [
                    q
                    for q in questions
                    if isinstance(q, dict)
                    and str(q.get("question_id") or "").strip()
                    and str(q.get("question_id") or "").strip() not in used_ids
                ]
                exercises = self._pick_questions(remaining, limit=max(1, exercises_limit)) if exercises_limit else []
                items.append(
                    {
                        "knowledge_point": point,
                        "success": bool(res.get("success")) if isinstance(res, dict) and "success" in res else True,
                        "difficulty": difficulty,
                        "examples": examples[:examples_limit] if examples_limit else [],
                        "exercises": exercises[:exercises_limit] if exercises_limit else [],
                        "raw_count": len(questions),
                        "provider": "question-bank",
                    }
                )
            except Exception as exc:  # pragma: no cover
                logger.exception("question_bank_search_failed", extra={"knowledge_point": point})
                items.append(
                    {
                        "knowledge_point": point,
                        "success": False,
                        "difficulty": difficulty,
                        "examples": [],
                        "exercises": [],
                        "raw_count": 0,
                        "provider": "question-bank",
                        "error": str(exc),
                    }
                )

        return {
            "topic": topic,
            "subject": applied_subject,
            "difficulty": difficulty,
            "examples_limit": examples_limit,
            "exercises_limit": exercises_limit,
            "items": items,
        }

    async def _tool_retrieve_knowledge(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or ctx.user_profile.preferences.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()

        if not is_llm_configured():
            return {
                "topic": topic,
                "subject": subject,
                "difficulty": difficulty,
                "definition": "",
                "key_points": [],
                "prerequisites": [],
                "common_mistakes": [],
                "methods": [],
                "source": "fallback",
                "note": "未配置模型，知识检索返回为空。",
            }

        prompt = f"""Generate factual notes for the knowledge point "{topic}" in "{subject}" that can be used in self-study materials.\n\nRequirements:\n- Output strict JSON only. Do not output Markdown or code fences.\n- Fields: definition(str), key_points(str[]), prerequisites(str[]), common_mistakes(str[]), methods(str[]).\n- Match the language of the subject/topic unless explicitly required otherwise.\n- Difficulty reference: {difficulty}\n"""
        text = await self._call_llm_text(
            messages=[
                {"role": "system", "content": "You are a rigorous subject teacher. Output JSON only."},
                {"role": "user", "content": prompt},
            ],
            model=self.config.summarizer_model,
            temperature=0.2,
            max_tokens=2600,
            response_format={"type": "json_object"},
        )
        obj = self._extract_json_obj(text)
        return {
            "topic": topic,
            "subject": subject,
            "difficulty": difficulty,
            "definition": str(obj.get("definition") or ""),
            "key_points": list(obj.get("key_points") or []),
            "prerequisites": list(obj.get("prerequisites") or []),
            "common_mistakes": list(obj.get("common_mistakes") or []),
            "methods": list(obj.get("methods") or []),
            "source": "llm",
        }

    async def _tool_search_examples(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 3)
        limit = max(1, min(5, limit))

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(12, limit * 4),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        picked = self._pick_questions(questions, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "examples": picked}

    async def _tool_search_exercises(self, args: Dict[str, Any], ctx: CompressedContext) -> Dict[str, Any]:
        topic = str(args.get("topic") or ctx.current_task).strip()
        subject = str(args.get("subject") or "").strip()
        difficulty = str(args.get("difficulty") or "中等").strip()
        limit = int(args.get("limit") or 10)
        limit = max(5, min(30, limit))

        used_ids: set[str] = set()
        prev = ctx.working_memory.get("search_examples")
        if isinstance(prev, dict):
            for q in prev.get("examples") or []:
                qid = str(q.get("question_id") or "").strip()
                if qid:
                    used_ids.add(qid)

        crawler = await get_crawler(subject=subject)
        res = await crawler.search_by_keyword(
            keyword=topic,
            subject=subject or crawler.subject,
            limit=max(20, limit * 3),
            difficulty=difficulty,
            max_pages=2,
            dedup_by_stem=True,
            min_quality_score=10,
            with_quality=True,
            strict_subject=True,
            require_difficulty=True,
        )
        questions = list(res.get("questions") or []) if isinstance(res, dict) else []
        filtered = [q for q in questions if str(q.get("question_id") or "").strip() not in used_ids]
        picked = self._pick_questions(filtered, limit=limit)
        return {"topic": topic, "subject": subject or crawler.subject, "difficulty": difficulty, "exercises": picked}
