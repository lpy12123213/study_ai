from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from backend.chat.tools_spec import TOOLS
from backend.core.logging_utils import get_logger
from backend.database.repositories.question.papers import list_papers, save_paper
from backend.database.repositories.question.question_cache import upsert_question_cache
from backend.core.subjects import DEFAULT_DIFFICULTY, normalize_difficulty, resolve_subject

logger = get_logger(__name__)


class ChatToolsMixin:
    current_subject = "高中数学"
    question_cache: Dict[str, Dict[str, Any]]

    def _tools_by_names(self, allowed_names: List[str]) -> List[Dict[str, Any]]:
        allowed = {n.strip() for n in (allowed_names or []) if (n or "").strip()}
        if not allowed:
            return []
        out: List[Dict[str, Any]] = []
        for tool in TOOLS:
            try:
                func = tool.get("function") or {}
                name = func.get("name")
                if name in allowed:
                    out.append(tool)
            except Exception:
                continue
        return out

    def _determine_tools_for_request(self, history: List[Dict[str, Any]], user_message: str) -> List[Dict[str, Any]]:
        plan = self._extract_last_plan_from_history(history)  # type: ignore[attr-defined]
        if plan is not None and self._is_confirmation_message(user_message):  # type: ignore[attr-defined]
            return TOOLS
        return self._tools_by_names(["get_available_filters", "search_questions"])

    async def _get_crawler(self, subject: Optional[str] = None, *, edu_level: str = ""):
        from backend.crawler.manager import get_crawler

        subj = resolve_subject(subject or self.current_subject, edu_level=edu_level, strict=True)
        self.current_subject = subj
        return await get_crawler(subject=subj, edu_level=edu_level, strict=True)

    def _lookup_tool_schema(self, tool_name: str) -> Optional[Dict[str, Any]]:
        name = (tool_name or "").strip()
        if not name:
            return None
        for tool in TOOLS:
            try:
                func = tool.get("function") or {}
                if func.get("name") == name:
                    params = func.get("parameters")
                    return params if isinstance(params, dict) else None
            except Exception:
                continue
        return None

    def _coerce_tool_args(self, tool_name: str, arguments: Any) -> Dict[str, Any]:
        if not isinstance(arguments, dict):
            return {}
        schema = self._lookup_tool_schema(tool_name)
        if not schema:
            return arguments
        coerced = self._coerce_with_schema(schema, arguments)
        return coerced if isinstance(coerced, dict) else arguments

    def _coerce_with_schema(self, schema: Any, value: Any) -> Any:
        if not isinstance(schema, dict):
            return value

        schema_type = schema.get("type")

        if schema_type == "object":
            if isinstance(value, str):
                s = value.strip()
                if s.startswith("{") or s.startswith("["):
                    try:
                        value = json.loads(s)
                    except Exception:
                        logger.debug("tool_schema_object_json_parse_failed", exc_info=True)
            if not isinstance(value, dict):
                return value
            props = schema.get("properties") or {}
            if not isinstance(props, dict):
                return value
            out = dict(value)
            for key, prop_schema in props.items():
                if key in value:
                    out[key] = self._coerce_with_schema(prop_schema, value.get(key))
            return out

        if schema_type == "array":
            if isinstance(value, str):
                s = value.strip()
                if s.startswith("[") or s.startswith("{"):
                    try:
                        value = json.loads(s)
                    except Exception:
                        logger.debug("tool_schema_array_json_parse_failed", exc_info=True)
            if not isinstance(value, list):
                return value
            item_schema = schema.get("items") or {}
            return [self._coerce_with_schema(item_schema, v) for v in value]

        if schema_type == "integer":
            return self._coerce_int(value)

        if schema_type == "number":
            return self._coerce_number(value)

        if schema_type == "boolean":
            return self._coerce_bool(value)

        return value

    def _coerce_int(self, value: Any) -> Any:
        try:
            if value is None:
                return value
            if isinstance(value, bool):
                return int(value)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value) if value.is_integer() else value
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return value
                try:
                    return int(s)
                except Exception:
                    try:
                        f = float(s)
                        return int(f) if f.is_integer() else value
                    except Exception:
                        return value
            return value
        except Exception:
            return value

    def _coerce_number(self, value: Any) -> Any:
        try:
            if value is None:
                return value
            if isinstance(value, bool):
                return float(int(value))
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                s = value.strip()
                if not s:
                    return value
                try:
                    return float(s)
                except Exception:
                    return value
            return value
        except Exception:
            return value

    def _coerce_bool(self, value: Any) -> Any:
        try:
            if value is None:
                return value
            if isinstance(value, bool):
                return value
            if isinstance(value, int):
                return bool(value)
            if isinstance(value, float):
                return bool(int(value))
            if isinstance(value, str):
                s = value.strip().lower()
                if s in {"true", "1", "yes", "y", "on"}:
                    return True
                if s in {"false", "0", "no", "n", "off", ""}:
                    return False
                return value
            return value
        except Exception:
            return value

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        sub_model: Optional[str] = None,
        user_id: str = "",
    ) -> Dict[str, Any]:
        try:
            arguments = self._coerce_tool_args(tool_name, arguments)

            def _as_int(value: Any, default: int) -> int:
                try:
                    if value is None or isinstance(value, bool):
                        return default
                    if isinstance(value, int):
                        return value
                    s = str(value).strip()
                    return int(s) if s else default
                except Exception:
                    return default

            def _as_float(value: Any) -> Optional[float]:
                try:
                    if value is None or isinstance(value, bool):
                        return None
                    if isinstance(value, (int, float)):
                        return float(value)
                    s = str(value).strip()
                    return float(s) if s else None
                except Exception:
                    return None

            if tool_name == "search_questions":
                edu_level = str(arguments.get("edu_level") or "").strip()
                crawler = await self._get_crawler(edu_level=edu_level)

                difficulty = normalize_difficulty(arguments.get("difficulty") or DEFAULT_DIFFICULTY, strict=True)
                learn_grade_id = _as_int(arguments.get("learn_grade_id", 0), 0)
                limit = _as_int(arguments.get("limit", 10), 10)
                max_pages = _as_int(arguments.get("max_pages", 2), 2)
                year = _as_int(arguments.get("year", 0), 0)
                province_id = _as_int(arguments.get("province_id", -1), -1)
                paper_type_id = _as_int(arguments.get("paper_type_id", 0), 0)
                term = _as_int(arguments.get("term", 0), 0)
                order_by = _as_int(arguments.get("order_by", 2), 2)
                min_quality_score = _as_int(arguments.get("min_quality_score", 0), 0)
                difficulty_value_min = _as_float(arguments.get("difficulty_value_min"))
                difficulty_value_max = _as_float(arguments.get("difficulty_value_max"))

                result = await crawler.search_by_keyword(
                    keyword=arguments.get("keyword", ""),
                    edu_level=edu_level,
                    difficulty=difficulty,
                    question_type=arguments.get("question_type", ""),
                    learn_grade=arguments.get("learn_grade", ""),
                    learn_grade_id=learn_grade_id,
                    textbook_version=arguments.get("textbook_version", ""),
                    limit=limit,
                    max_pages=max_pages,
                    year=year,
                    province=arguments.get("province", ""),
                    province_id=province_id,
                    paper_type_id=paper_type_id,
                    term=term,
                    order_by=order_by,
                    source_contains=arguments.get("source_contains", ""),
                    stem_contains=arguments.get("stem_contains", ""),
                    knowledge_contains=arguments.get("knowledge_contains", ""),
                    elective_mode=arguments.get("elective_mode", ""),
                    elective_keywords=arguments.get("elective_keywords"),
                    exclude_elective=arguments.get("exclude_elective", False),
                    dedup_by_stem=arguments.get("dedup_by_stem", False),
                    min_quality_score=min_quality_score,
                    difficulty_value_min=difficulty_value_min,
                    difficulty_value_max=difficulty_value_max,
                    require_difficulty=True,
                    strict_subject=True,
                )
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            if tool_name == "get_available_filters":
                edu_level = str(arguments.get("edu_level") or "").strip()
                subject_input = str(arguments.get("subject") or self.current_subject).strip()
                crawler = await self._get_crawler(subject=subject_input, edu_level=edu_level)
                result = await crawler.get_available_filters()
                result["current_subject"] = getattr(crawler, "subject", self.current_subject)
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            if tool_name == "compose_paper_blueprint":
                edu_level = str(arguments.get("edu_level") or "").strip()
                subject_input = str(arguments.get("subject") or self.current_subject).strip()
                try:
                    subject = resolve_subject(subject_input, edu_level=edu_level, strict=True)
                except ValueError as exc:
                    return {
                        "success": False,
                        "error": str(exc),
                        "current_subject": self.current_subject,
                        "allowed_edu_levels": ["小学", "初中", "高中"],
                    }

                learn_grade_id = _as_int(arguments.get("learn_grade_id", 0), 0)
                year = _as_int(arguments.get("year", 0), 0)
                province_id = _as_int(arguments.get("province_id", -1), -1)
                paper_type_id = _as_int(arguments.get("paper_type_id", 0), 0)
                term = _as_int(arguments.get("term", 0), 0)
                order_by = _as_int(arguments.get("order_by", 2), 2)
                max_pages = _as_int(arguments.get("max_pages", 2), 2)
                per_slot_expand = _as_int(arguments.get("per_slot_expand", 3), 3)
                min_quality_score = _as_int(arguments.get("min_quality_score", 0), 0)

                crawler = await self._get_crawler(subject=subject, edu_level=edu_level)
                result = await crawler.compose_paper_blueprint(
                    blueprint=arguments.get("blueprint") or [],
                    subject=subject,
                    edu_level=edu_level,
                    learn_grade=arguments.get("learn_grade", ""),
                    learn_grade_id=learn_grade_id,
                    textbook_version=arguments.get("textbook_version", ""),
                    elective_mode=arguments.get("elective_mode", ""),
                    elective_keywords=arguments.get("elective_keywords"),
                    exclude_elective=arguments.get("exclude_elective", False),
                    year=year,
                    province=arguments.get("province", ""),
                    province_id=province_id,
                    paper_type_id=paper_type_id,
                    term=term,
                    order_by=order_by,
                    max_pages=max_pages,
                    per_slot_expand=per_slot_expand,
                    min_quality_score=min_quality_score,
                    dedup_by_stem=arguments.get("dedup_by_stem", True),
                    strict_subject=arguments.get("strict_subject", True),
                )
                result["current_subject"] = subject
                if edu_level:
                    result["applied_edu_level"] = edu_level
                return result

            if tool_name == "create_paper":
                uid = str(user_id or "").strip()
                if not uid:
                    return {"success": False, "error": "missing_user_id"}
                questions = [{"question_id": qid} for qid in (arguments.get("question_ids") or [])]
                paper_id = await save_paper(
                    user_id=uid,
                    paper_name=arguments.get("paper_name", "未命名试卷"),
                    questions=questions,
                )
                return {"success": True, "paper_id": paper_id, "message": f"试卷创建成功，ID: {paper_id}"}

            if tool_name == "get_papers":
                uid = str(user_id or "").strip()
                if not uid:
                    return {"success": False, "error": "missing_user_id"}
                papers = await list_papers(
                    user_id=uid,
                    limit=int(arguments.get("limit") or 10),
                )
                return {"success": True, "papers": papers, "count": len(papers)}

            if tool_name == "get_question_detail":
                crawler = await self._get_crawler()
                return await crawler.get_question_detail(question_id=arguments.get("question_id", ""))

            if tool_name == "batch_get_question_details":
                crawler = await self._get_crawler()
                result = await crawler.batch_get_question_details(question_ids=arguments.get("question_ids", []))
                for q in result.get("questions", []) if isinstance(result, dict) else []:
                    qid = q.get("question_id") if isinstance(q, dict) else None
                    if qid:
                        self.question_cache[str(qid)] = q
                try:
                    await upsert_question_cache(result.get("questions", []) if isinstance(result, dict) else [])
                except Exception:
                    logger.exception("upsert_question_cache_failed")
                return result

            if tool_name == "select_best_question":
                from backend.mcp.core.sub_ai_selector import select_best_question as sub_ai_select

                question_ids = list(arguments.get("question_ids") or [])[:5]
                requirement = str(arguments.get("requirement") or "")
                sub_model_value = (sub_model or "").strip() or None

                questions: List[Dict[str, Any]] = []
                missing_ids: List[str] = []
                for qid in question_ids:
                    qid_s = str(qid or "").strip()
                    if not qid_s:
                        continue
                    if qid_s in self.question_cache:
                        questions.append(self.question_cache[qid_s])
                    else:
                        missing_ids.append(qid_s)

                if missing_ids:
                    crawler = await self._get_crawler()
                    details_result = await crawler.batch_get_question_details(missing_ids)
                    for q in details_result.get("questions", []) if isinstance(details_result, dict) else []:
                        qid = q.get("question_id") if isinstance(q, dict) else None
                        if qid:
                            self.question_cache[str(qid)] = q
                            questions.append(q)
                    try:
                        await upsert_question_cache(
                            details_result.get("questions", []) if isinstance(details_result, dict) else []
                        )
                    except Exception:
                        logger.exception("upsert_question_cache_failed")

                if not questions:
                    return {"success": False, "error": "无法获取候选题目详情"}

                result = await sub_ai_select(questions=questions, requirement=requirement, model=sub_model_value)
                if result.get("success"):
                    result["message"] = f"子AI已从{len(questions)}道候选题目中选择了最符合要求的题目"
                return result

            return {"success": False, "error": f"未知工具: {tool_name}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
