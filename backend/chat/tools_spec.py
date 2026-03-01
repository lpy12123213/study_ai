from __future__ import annotations

from typing import Any, Dict, List


TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_questions",
            "description": "搜索题目。根据关键词、难度、题型等条件搜索组卷网上的题目。返回题目ID列表和基本信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词，如'函数'、'导数'、'三角函数'等"},
                    "edu_level": {
                        "type": "string",
                        "enum": ["小学", "初中", "高中", ""],
                        "description": "学段筛选，可选：小学/初中/高中（指定后将严格校验）",
                        "default": "",
                    },
                    "difficulty": {
                        "type": "string",
                        "enum": ["简单", "中等", "困难", ""],
                        "description": "难度等级筛选，可选。重要：难度系数越小越难（困难 < 中等 < 简单）。",
                    },
                    "question_type": {"type": "string", "description": "题型，如'选择题'、'填空题'、'解答题'等，可选"},
                    "learn_grade": {
                        "type": "string",
                        "description": "年级筛选（可选，如：高一/高二/高三/七年级等；建议先通过 get_available_filters 获取可用项）",
                        "default": "",
                    },
                    "learn_grade_id": {"type": "integer", "description": "年级ID（高级；优先级高于 learn_grade）"},
                    "textbook_version": {"type": "string", "description": "教材版本（可选；建议先通过 get_available_filters 获取可用项）"},
                    "province": {"type": "string", "description": "省份（可选；建议先通过 get_available_filters 获取可用项）"},
                    "province_id": {"type": "integer", "description": "省份ID（高级；优先级高于 province）"},
                    "paper_type_id": {"type": "integer", "description": "试卷类型ID（可选；建议先通过 get_available_filters 获取可用项）"},
                    "year": {"type": "integer", "description": "年份（可选；如 2023）"},
                    "term": {"type": "integer", "description": "学期/月份（可选；0 表示不限）"},
                    "order_by": {"type": "integer", "description": "排序方式（可选；默认 2）"},
                    "source_contains": {"type": "string", "description": "来源包含关键字（可选）"},
                    "stem_contains": {"type": "string", "description": "题干包含关键字（可选）"},
                    "knowledge_contains": {"type": "string", "description": "知识点包含关键字（可选）"},
                    "elective_mode": {
                        "type": "string",
                        "enum": ["include", "exclude", ""],
                        "description": "选修内容处理：include/exclude",
                        "default": "",
                    },
                    "elective_keywords": {"type": "array", "items": {"type": "string"}, "description": "选修关键词列表（可选）"},
                    "exclude_elective": {"type": "boolean", "description": "是否排除选修内容（可选）"},
                    "dedup_by_stem": {"type": "boolean", "description": "是否按题干去重（可选）"},
                    "min_quality_score": {"type": "integer", "description": "最低题干质量分（0-100，可选）"},
                    "difficulty_value_min": {"type": "number", "description": "难度系数下限（越小越难，可选）"},
                    "difficulty_value_max": {"type": "number", "description": "难度系数上限（越小越难，可选）"},
                    "limit": {"type": "integer", "description": "返回题目数量（默认10，建议5-15）"},
                    "max_pages": {"type": "integer", "description": "最多翻页数（默认2）"},
                    "strict_subject": {"type": "boolean", "description": "是否严格校验学科（默认 true）"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_available_filters",
            "description": "获取当前学科可用筛选项（年级/教材/题型等），避免写死 ID。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "学科名称（可选，默认当前学科）"},
                    "edu_level": {"type": "string", "enum": ["小学", "初中", "高中", ""], "default": ""},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compose_paper_blueprint",
            "description": "根据“蓝图槽位”批量搜索并组装题目ID列表（优先使用）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "subject": {"type": "string", "description": "学科（可选）"},
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
                        "description": "槽位列表，每个槽位描述要的题型/数量/难度/关键词等",
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
            "description": "批量获取题目详情（最多10个）。用于内部判断/二次筛选（不要把题目原文直接发给用户）。",
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
            "description": "【子AI选题】从候选题目中选择最符合要求的一道（2-5个候选）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question_ids": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5},
                    "requirement": {"type": "string", "description": "选题要求描述"},
                },
                "required": ["question_ids", "requirement"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_paper",
            "description": "创建试卷（只提交题目ID列表）。",
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
            "description": "查看已保存试卷。",
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
            "description": "获取单题详情（仅调试用）。",
            "parameters": {"type": "object", "properties": {"question_id": {"type": "string"}}, "required": ["question_id"]},
        },
    },
]

