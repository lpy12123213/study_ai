from __future__ import annotations

from typing import Any, Dict, List

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_questions",
            "description": (
                "Search question-bank items by keyword and filters. Return question IDs and metadata only; use "
                "small limits for planning probes unless executing a confirmed paper plan."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "Search keyword, for example 函数, 导数, 三角函数."},
                    "edu_level": {
                        "type": "string",
                        "enum": ["小学", "初中", "高中", ""],
                        "description": "Education-level filter. Allowed Chinese values: 小学, 初中, 高中. Strictly validated when set.",
                        "default": "",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["简单", "中等", "困难", ""],
                        "description": (
                            "Difficulty-level filter. Allowed Chinese values: 简单, 中等, 困难. Important: a lower "
                            "difficulty coefficient means a harder question."
                        ),
                    },
                    "question_type": {"type": "string", "description": "Question type, for example 选择题, 填空题, 解答题. Optional."},
                    "learn_grade": {
                        "type": "string",
                        "description": "Grade filter, for example 高一, 高二, 高三, 七年级. Prefer get_available_filters before setting it.",
                        "default": "",
                    },
                    "learn_grade_id": {"type": "integer", "description": "Grade ID. Advanced; takes priority over learn_grade."},
                    "textbook_version": {
                        "type": "string",
                        "description": "Textbook version. Optional; prefer get_available_filters before setting it.",
                    },
                    "province": {
                        "type": "string",
                        "description": "Province filter. Optional; prefer get_available_filters before setting it.",
                    },
                    "province_id": {"type": "integer", "description": "Province ID. Advanced; takes priority over province."},
                    "paper_type_id": {
                        "type": "integer",
                        "description": "Paper-type ID. Optional; prefer get_available_filters before setting it.",
                    },
                    "year": {"type": "integer", "description": "Year filter, for example 2023. Optional."},
                    "term": {"type": "integer", "description": "Term/month filter. Optional; 0 means no restriction."},
                    "order_by": {"type": "integer", "description": "Sort mode. Optional; default is 2."},
                    "source_contains": {"type": "string", "description": "Require source metadata to contain this keyword. Optional."},
                    "stem_contains": {"type": "string", "description": "Require the stem to contain this keyword. Optional."},
                    "knowledge_contains": {"type": "string", "description": "Require knowledge-point metadata to contain this keyword. Optional."},
                    "elective_mode": {
                        "type": "string",
                        "enum": ["include", "exclude", ""],
                        "description": "Elective-content handling: include or exclude.",
                        "default": "",
                    },
                    "elective_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional elective keyword list.",
                    },
                    "exclude_elective": {"type": "boolean", "description": "Whether to exclude elective content. Optional."},
                    "dedup_by_stem": {"type": "boolean", "description": "Whether to deduplicate by stem. Optional."},
                    "min_quality_score": {"type": "integer", "description": "Minimum stem quality score, 0-100. Optional."},
                    "difficulty_value_min": {"type": "number", "description": "Minimum difficulty coefficient. Lower means harder. Optional."},
                    "difficulty_value_max": {"type": "number", "description": "Maximum difficulty coefficient. Lower means harder. Optional."},
                    "limit": {"type": "integer", "description": "Number of items to return. Default 10; recommended 5-15."},
                    "max_pages": {"type": "integer", "description": "Maximum pages to scan. Default 2."},
                    "strict_subject": {"type": "boolean", "description": "Whether to strictly validate the subject. Default true."},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_filters",
            "description": "Fetch available filters for the current subject, such as grade, textbook, and question type. Use this to avoid hard-coded IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject name. Optional; defaults to the current subject."},
                    "edu_level": {"type": "string", "enum": ["小学", "初中", "高中", ""], "default": ""},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compose_paper_blueprint",
            "description": "Batch search and assemble question IDs from blueprint slots. Prefer this after the user confirms the paper plan.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "Subject. Optional."},
                    "edu_level": {"type": "string", "enum": ["小学", "初中", "高中", ""], "default": ""},
                    "learn_grade": {"type": "string"},
                    "learn_grade_id": {"type": "integer"},
                    "textbook_version": {"type": "string"},
                    "province": {"type": "string"},
                    "province_id": {"type": "integer"},
                    "paper_type_id": {"type": "integer"},
                    "year": {"type": "integer"},
                    "term": {"type": "integer"},
                    "order_by": {"type": "integer"},
                    "elective_mode": {"type": "string", "enum": ["include", "exclude", ""], "default": ""},
                    "elective_keywords": {"type": "array", "items": {"type": "string"}},
                    "exclude_elective": {"type": "boolean"},
                    "max_pages": {"type": "integer"},
                    "per_slot_expand": {"type": "integer"},
                    "min_quality_score": {"type": "integer"},
                    "dedup_by_stem": {"type": "boolean"},
                    "strict_subject": {"type": "boolean"},
                    "blueprint": {
                        "type": "array",
                        "description": "Blueprint slots. Each slot describes desired question type, count, difficulty, keyword, and filters.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "section": {"type": "string"},
                                "keyword": {"type": "string"},
                                "knowledge_point": {"type": "string"},
                                "count": {"type": "integer"},
                                "difficulty": {"type": "string"},
                                "question_type": {"type": "string"},
                                "source_contains": {"type": "string"},
                                "stem_contains": {"type": "string"},
                                "knowledge_contains": {"type": "string"},
                                "max_pages": {"type": "integer"},
                            },
                            "required": ["section", "keyword", "count"],
                        },
                    },
                },
                "required": ["blueprint"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "batch_get_question_details",
            "description": "Batch fetch question details, max 10. Use only for internal judgment or second-pass filtering; do not send full original question text to the user.",
            "parameters": {
                "type": "object",
                "properties": {"question_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 10}},
                "required": ["question_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "select_best_question",
            "description": "Sub-AI selection: choose the best-fitting question from 2-5 candidate IDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
                    "requirement": {"type": "string", "description": "Selection requirement description."},
                },
                "required": ["question_ids", "requirement"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_paper",
            "description": "Create a paper by submitting question IDs only. Call this only after user confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_name": {"type": "string"},
                    "question_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["paper_name", "question_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_papers",
            "description": "List saved papers.",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_question_detail",
            "description": "Fetch a single question detail. Debug-only; do not use for normal user-facing disclosure.",
            "parameters": {
                "type": "object",
                "properties": {"question_id": {"type": "string"}},
                "required": ["question_id"],
            },
        },
    },
]
