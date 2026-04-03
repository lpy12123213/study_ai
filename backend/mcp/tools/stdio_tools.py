"""MCP stdio tool definitions (Tool list).

This file is intentionally split out of `backend/mcp/stdio_server.py` to keep the stdio entrypoint small.
"""

from __future__ import annotations

from typing import List

from mcp.types import Tool


def get_stdio_tools() -> List[Tool]:
    return [
        Tool(
            name="search_questions_by_keyword",
            description="""【推荐】通过关键词搜索题目，直接返回完整题目信息。
返回内容包括：题号、题型、难度(含数值)、知识点列表、来源、日期、题干内容。
搜索结果已包含题干，无需再调用 get_question_details。
公式已转换为 LaTeX 格式。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {"type": "string", "description": "搜索关键词"},
                    "subject": {
                        "type": "string",
                        "description": "学科全名（如：高中数学、初中物理、小学语文），会自动切换学科",
                        "default": "",
                    },
                    "edu_level": {
                        "type": "string",
                        "description": "学段筛选（可选：小学/初中/高中）",
                        "enum": ["小学", "初中", "高中", ""],
                        "default": "",
                    },
                    "difficulty": {
                        "type": "string",
                        "description": "难度（可选：简单/中等/困难，默认中等）",
                        "default": "中等",
                    },
                    "question_type": {
                        "type": "string",
                        "description": "题型（选择题/填空题/解答题等）",
                        "default": "",
                    },
                    "learn_grade": {
                        "type": "string",
                        "description": "年级筛选（可选，如：高一/高二/高三/七年级等；建议先用 get_available_filters 查看可用年级/ID）",
                        "default": "",
                    },
                    "learn_grade_id": {
                        "type": "integer",
                        "description": "年级ID（高级；优先级高于 learn_grade）",
                        "default": 0,
                    },
                    "textbook_version": {
                        "type": "string",
                        "description": "教材版本/题库分类（可选，如：人教版/外研版/北师大版；建议先用 get_available_filters 查看可用项）",
                        "default": "",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量限制",
                        "default": 10,
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "最多翻页数（默认 2 页）",
                        "default": 2,
                    },
                    "year": {
                        "type": "integer",
                        "description": "年份过滤（如 2024；0 表示不限）",
                        "default": 0,
                    },
                    "source_contains": {
                        "type": "string",
                        "description": "来源包含关键字（如：高考、期末、北京等）",
                        "default": "",
                    },
                    "stem_contains": {
                        "type": "string",
                        "description": "题干包含关键字（可选）",
                        "default": "",
                    },
                    "knowledge_contains": {
                        "type": "string",
                        "description": "知识点包含关键字（可选）",
                        "default": "",
                    },
                    "exclude_elective": {
                        "type": "boolean",
                        "description": "排除包含“选修/选择性必修”等标记的题目（基于来源/知识点/题干启发式过滤）",
                        "default": False,
                    },
                    "elective_mode": {
                        "type": "string",
                        "description": "选修过滤模式（include=不限；exclude=排除选修；only=仅选修）。注意：如果同时传 exclude_elective=true 且 elective_mode 为空，则等价于 exclude。",
                        "enum": ["", "include", "exclude", "only"],
                        "default": "",
                    },
                    "elective_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：自定义选修识别关键词（默认：选修/选择性必修/选必）",
                    },
                    "dedup_by_stem": {
                        "type": "boolean",
                        "description": "按题干指纹去重（避免同质题/重复题）",
                        "default": False,
                    },
                    "min_quality_score": {
                        "type": "integer",
                        "description": "题目质量分阈值（0-100，越高越严格；会过滤题干过短/公式转换缺失/图片过多等）",
                        "default": 0,
                    },
                    "with_quality": {
                        "type": "boolean",
                        "description": "是否在返回结果中附带 quality_score/quality_flags",
                        "default": True,
                    },
                    "difficulty_value_min": {
                        "type": "number",
                        "description": "难度系数下限（可选）。注意：系数越小越难；题目没有难度系数时不会被剔除",
                    },
                    "difficulty_value_max": {
                        "type": "number",
                        "description": "难度系数上限（可选）。注意：系数越小越难；题目没有难度系数时不会被剔除",
                    },
                    "province": {
                        "type": "string",
                        "description": "地区（可选，如：北京/北京市/全国；建议先用 get_available_filters 查看 provinces；同时传 province_id 时以 province_id 为准）",
                        "default": "",
                    },
                    "province_id": {
                        "type": "integer",
                        "description": "地区ID（高级；-1 表示不限）",
                        "default": -1,
                    },
                    "paper_type_id": {
                        "type": "integer",
                        "description": "试卷类型ID（高级；0 表示不限）",
                        "default": 0,
                    },
                    "term": {
                        "type": "integer",
                        "description": "学期（高级；0 表示不限）",
                        "default": 0,
                    },
                    "order_by": {
                        "type": "integer",
                        "description": "排序方式（高级；默认 2）",
                        "default": 2,
                    },
                },
                "required": ["keyword"],
            },
        ),
        Tool(
            name="search_questions_by_knowledge",
            description="""【推荐】通过知识点搜索题目，直接返回完整题目信息。
返回内容包括：题号、题型、难度(含数值)、知识点列表、来源、日期、题干内容。
搜索结果已包含题干，无需再调用 get_question_details。
公式已转换为 LaTeX 格式。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "knowledge_point": {
                        "type": "string",
                        "description": "知识点名称",
                    },
                    "subject": {
                        "type": "string",
                        "description": "学科全名（如：高中数学、初中物理）",
                    },
                    "edu_level": {
                        "type": "string",
                        "description": "学段筛选（可选：小学/初中/高中）",
                        "enum": ["小学", "初中", "高中", ""],
                        "default": "",
                    },
                    "difficulty": {
                        "type": "string",
                        "description": "难度（可选：简单/中等/困难，默认中等）",
                        "default": "中等",
                    },
                    "question_type": {
                        "type": "string",
                        "description": "题型（选择题/填空题/解答题等）",
                        "default": "",
                    },
                    "learn_grade": {
                        "type": "string",
                        "description": "年级筛选（可选，如：高一/高二/高三/七年级等；建议先用 get_available_filters 查看可用年级/ID）",
                        "default": "",
                    },
                    "learn_grade_id": {
                        "type": "integer",
                        "description": "年级ID（高级；优先级高于 learn_grade）",
                        "default": 0,
                    },
                    "textbook_version": {
                        "type": "string",
                        "description": "教材版本/题库分类（可选，如：人教版/外研版/北师大版；建议先用 get_available_filters 查看可用项）",
                        "default": "",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量限制",
                        "default": 10,
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "最多翻页数（默认 2 页）",
                        "default": 2,
                    },
                    "year": {
                        "type": "integer",
                        "description": "年份过滤（如 2024；0 表示不限）",
                        "default": 0,
                    },
                    "source_contains": {
                        "type": "string",
                        "description": "来源包含关键字（如：高考、期末、北京等）",
                        "default": "",
                    },
                    "stem_contains": {
                        "type": "string",
                        "description": "题干包含关键字（可选）",
                        "default": "",
                    },
                    "knowledge_contains": {
                        "type": "string",
                        "description": "知识点包含关键字（可选）",
                        "default": "",
                    },
                    "exclude_elective": {
                        "type": "boolean",
                        "description": "排除包含“选修/选择性必修”等标记的题目（基于来源/知识点/题干启发式过滤）",
                        "default": False,
                    },
                    "elective_mode": {
                        "type": "string",
                        "description": "选修过滤模式（include=不限；exclude=排除选修；only=仅选修）。注意：如果同时传 exclude_elective=true 且 elective_mode 为空，则等价于 exclude。",
                        "enum": ["", "include", "exclude", "only"],
                        "default": "",
                    },
                    "elective_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选：自定义选修识别关键词（默认：选修/选择性必修/选必）",
                    },
                    "dedup_by_stem": {
                        "type": "boolean",
                        "description": "按题干指纹去重（避免同质题/重复题）",
                        "default": False,
                    },
                    "min_quality_score": {
                        "type": "integer",
                        "description": "题目质量分阈值（0-100，越高越严格；会过滤题干过短/公式转换缺失/图片过多等）",
                        "default": 0,
                    },
                    "with_quality": {
                        "type": "boolean",
                        "description": "是否在返回结果中附带 quality_score/quality_flags",
                        "default": True,
                    },
                    "difficulty_value_min": {
                        "type": "number",
                        "description": "难度系数下限（可选）。注意：系数越小越难；题目没有难度系数时不会被剔除",
                    },
                    "difficulty_value_max": {
                        "type": "number",
                        "description": "难度系数上限（可选）。注意：系数越小越难；题目没有难度系数时不会被剔除",
                    },
                    "province": {
                        "type": "string",
                        "description": "地区（可选，如：北京/北京市/全国；建议先用 get_available_filters 查看 provinces；同时传 province_id 时以 province_id 为准）",
                        "default": "",
                    },
                    "province_id": {
                        "type": "integer",
                        "description": "地区ID（高级；-1 表示不限）",
                        "default": -1,
                    },
                    "paper_type_id": {
                        "type": "integer",
                        "description": "试卷类型ID（高级；0 表示不限）",
                        "default": 0,
                    },
                    "term": {
                        "type": "integer",
                        "description": "学期（高级；0 表示不限）",
                        "default": 0,
                    },
                    "order_by": {
                        "type": "integer",
                        "description": "排序方式（高级；默认 2）",
                        "default": 2,
                    },
                },
                "required": ["knowledge_point", "subject"],
            },
        ),
        Tool(
            name="filter_questions",
            description="根据已搜索的题目列表进行二次过滤（难度、题型等）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目编号列表",
                    },
                    "difficulty": {
                        "type": "string",
                        "description": "难度等级（简单/中等/困难）",
                        "enum": ["简单", "中等", "困难", ""],
                        "default": "",
                    },
                    "question_type": {
                        "type": "string",
                        "description": "题型（选择题/填空题/解答题等）",
                        "default": "",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量限制",
                        "default": 10,
                    },
                },
                "required": ["question_ids"],
            },
        ),
        Tool(
            name="get_question_info",
            description="获取单个题目的缓存信息。注意：搜索结果已包含完整信息，通常无需调用此工具。",
            inputSchema={
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "description": "题目编号",
                    }
                },
                "required": ["question_id"],
            },
        ),
        Tool(
            name="create_paper",
            description="创建试卷（保存题目编号组合到本地）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目编号列表",
                    },
                    "paper_name": {
                        "type": "string",
                        "description": "试卷名称",
                    },
                },
                "required": ["question_ids", "paper_name"],
            },
        ),
        Tool(
            name="select_best_question",
            description="""【子AI选题】从搜索结果中选择最符合要求的题目。
直接传入搜索返回的题目ID即可，搜索结果已包含题干信息。
子AI会分析题目内容并给出选择理由。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "候选题目ID列表（2-5个，来自搜索结果）",
                    },
                    "requirement": {
                        "type": "string",
                        "description": "选题要求描述（如：需要一道考查顶点式应用的中等难度题目）",
                    },
                },
                "required": ["question_ids", "requirement"],
            },
        ),
        Tool(
            name="get_question_details",
            description="""【备用】单独获取题目详情页信息。
注意：搜索结果已包含题干、难度、知识点等信息，通常无需调用此工具。
仅在需要获取答案解析（需登录）时使用。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目编号列表（最多10个）",
                    }
                },
                "required": ["question_ids"],
            },
        ),
        Tool(
            name="export_to_zujuan",
            description="""导出题目到组卷网题篮。需要先登录（运行 scripts/登录组卷网.bat，可选传入学科名）。
导出成功后可在 https://zujuan.xkw.com/basket/ 查看并生成试卷。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目编号列表",
                    },
                    "subject": {
                        "type": "string",
                        "description": "学科全名（可选，如：高中数学、初中物理、小学语文；不填则使用当前学科）",
                        "default": "",
                    },
                    "paper_name": {
                        "type": "string",
                        "description": "试卷名称（可选）",
                        "default": "AI组卷",
                    },
                },
                "required": ["question_ids"],
            },
        ),
        Tool(
            name="review_paper",
            description="""【审卷人】调用子 AI 对试卷/题目进行审查，返回可读的审查意见。
审查内容：题干规范性、难度分布、知识点覆盖、疑似错题、重复题等。

**重要**：请务必将用户的具体要求通过 focus 参数传递给审卷人！
例如：用户说"帮我检查这套卷子难度是否适合中考"，则 focus 应填写"检查难度是否适合中考"。

注意：题干内容会发送到第三方模型，图片和公式可能无法正确显示。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "paper_id": {
                        "type": "integer",
                        "description": "试卷ID（可选，与 question_ids 二选一）",
                    },
                    "question_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "题目ID列表（可选，与 paper_id 二选一）",
                    },
                    "paper_name": {
                        "type": "string",
                        "description": "试卷名称（可选，用于提示模型）",
                        "default": "",
                    },
                    "subject": {
                        "type": "string",
                        "description": "学科全名（可选，如：高中数学、初中物理、小学语文；不填则使用当前学科）",
                        "default": "",
                    },
                    "focus": {
                        "type": "string",
                        "description": "【重要】用户的审查要求，必须如实传递用户原话或核心诉求（如：检查是否超纲、难度是否适合高考、有没有偏题怪题等）",
                        "default": "",
                    },
                    "strictness": {
                        "type": "integer",
                        "description": "严格度 1-5（越高越苛刻）",
                        "default": 3,
                    },
                    "max_questions": {
                        "type": "integer",
                        "description": "最多审查题目数（避免提示词过长）",
                        "default": 20,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="list_subjects",
            description="列出所有支持的学科（小学/初中/高中各科）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "edu_level": {
                        "type": "string",
                        "description": "学段筛选（可选：小学/初中/高中）",
                        "default": "",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="set_subject",
            description="切换当前学科。注意：搜索时传入 subject 参数会自动切换，通常无需单独调用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "学科全名（如：高中数学、初中物理、小学语文）",
                    },
                },
                "required": ["subject"],
            },
        ),
        Tool(
            name="get_current_subject",
            description="获取当前设置的学科。默认为高中数学。",
            inputSchema={
                "type": "object",
                "properties": {},
                "required": [],
            },
        ),
        Tool(
            name="get_available_filters",
            description="获取当前学科下可用的筛选项（年级/试卷类型/教材版本/题型等），用于下拉选择，避免写死ID。",
            inputSchema={
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "学科全名（可选，不填则使用当前学科；填写会自动切换）",
                        "default": "",
                    },
                    "edu_level": {
                        "type": "string",
                        "description": "学段校验（可选：小学/初中/高中；填写后会严格校验学段与学科匹配）",
                        "enum": ["小学", "初中", "高中", ""],
                        "default": "",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="compose_paper_blueprint",
            description="根据“组卷蓝图”批量搜索并组装题目ID列表（支持年级/教材版本/选修过滤/去重/质量阈值/严学科约束）。返回分段选题结果与精简预览。",
            inputSchema={
                "type": "object",
                "properties": {
                    "blueprint": {
                        "type": "array",
                        "description": "组卷蓝图（多个检索槽位）",
                        "items": {
                            "type": "object",
                            "properties": {
                                "keyword": {
                                    "type": "string",
                                    "description": "关键词（与 knowledge_point 二选一）",
                                    "default": "",
                                },
                                "knowledge_point": {
                                    "type": "string",
                                    "description": "知识点（与 keyword 二选一）",
                                    "default": "",
                                },
                                "count": {
                                    "type": "integer",
                                    "description": "本槽位需要的题目数量",
                                    "default": 1,
                                },
                                "difficulty": {
                                    "type": "string",
                                    "description": "难度（简单/中等/困难；可选）",
                                    "default": "",
                                },
                                "question_type": {
                                    "type": "string",
                                    "description": "题型（可选）",
                                    "default": "",
                                },
                                "source_contains": {
                                    "type": "string",
                                    "description": "来源包含（可选）",
                                    "default": "",
                                },
                                "stem_contains": {
                                    "type": "string",
                                    "description": "题干包含（可选）",
                                    "default": "",
                                },
                                "knowledge_contains": {
                                    "type": "string",
                                    "description": "知识点包含（可选）",
                                    "default": "",
                                },
                                "max_pages": {
                                    "type": "integer",
                                    "description": "本槽位最多翻页数（可选，覆盖全局 max_pages）",
                                    "default": 0,
                                },
                            },
                        },
                    },
                    "subject": {
                        "type": "string",
                        "description": "学科全名（可选，不填则使用当前学科；填写会自动切换）",
                        "default": "",
                    },
                    "edu_level": {
                        "type": "string",
                        "description": "学段校验（可选：小学/初中/高中；填写后会严格校验学段与学科匹配）",
                        "enum": ["小学", "初中", "高中", ""],
                        "default": "",
                    },
                    "learn_grade": {
                        "type": "string",
                        "description": "年级名称（可选）",
                        "default": "",
                    },
                    "learn_grade_id": {
                        "type": "integer",
                        "description": "年级ID（可选，优先级高于 learn_grade）",
                        "default": 0,
                    },
                    "textbook_version": {
                        "type": "string",
                        "description": "教材版本/题库分类（可选）",
                        "default": "",
                    },
                    "elective_mode": {
                        "type": "string",
                        "description": "选修过滤模式（include/exclude/only）",
                        "default": "",
                    },
                    "elective_keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "自定义选修识别关键词（可选）",
                    },
                    "exclude_elective": {
                        "type": "boolean",
                        "description": "兼容旧参数：true 等价于 elective_mode=exclude（当 elective_mode 为空时）",
                        "default": False,
                    },
                    "year": {
                        "type": "integer",
                        "description": "年份过滤（可选，0 表示不限）",
                        "default": 0,
                    },
                    "province": {
                        "type": "string",
                        "description": "地区（可选，如：北京/北京市/全国；建议先用 get_available_filters 查看 provinces；同时传 province_id 时以 province_id 为准）",
                        "default": "",
                    },
                    "province_id": {
                        "type": "integer",
                        "description": "地区ID（可选，-1 表示不限）",
                        "default": -1,
                    },
                    "paper_type_id": {
                        "type": "integer",
                        "description": "试卷类型ID（可选，0 表示不限）",
                        "default": 0,
                    },
                    "term": {
                        "type": "integer",
                        "description": "学期（可选，0 表示不限）",
                        "default": 0,
                    },
                    "order_by": {
                        "type": "integer",
                        "description": "排序方式（可选，默认 2）",
                        "default": 2,
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "全局最多翻页数（默认 2）",
                        "default": 2,
                    },
                    "per_slot_expand": {
                        "type": "integer",
                        "description": "每个槽位扩展倍数（先多抓再筛选；默认 3）",
                        "default": 3,
                    },
                    "min_quality_score": {
                        "type": "integer",
                        "description": "最小质量分（0-100；0 表示不过滤）",
                        "default": 0,
                    },
                    "dedup_by_stem": {
                        "type": "boolean",
                        "description": "按题干去重（避免同质题）",
                        "default": True,
                    },
                    "strict_subject": {
                        "type": "boolean",
                        "description": "严学科约束（防止跨学段混入）",
                        "default": True,
                    },
                },
                "required": ["blueprint"],
            },
        ),
        Tool(
            name="retrieve_knowledge",
            description="检索/生成知识点要点（定义/关键点/前置/误区/方法），用于自学资料或教学设计。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "知识点名称/主题"},
                    "subject": {"type": "string", "description": "学科全名（可选）", "default": ""},
                    "difficulty": {"type": "string", "description": "难度（简单/中等/困难）", "default": "中等"},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="search_examples",
            description="搜索例题（优先挑选图片少、题干清晰的题目）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "知识点/关键词"},
                    "subject": {"type": "string", "description": "学科全名（可选，不填则用当前学科）", "default": ""},
                    "difficulty": {"type": "string", "description": "难度（简单/中等/困难）", "default": "中等"},
                    "limit": {"type": "integer", "description": "返回数量（1-5）", "default": 3},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="search_exercises",
            description="搜索练习题（仅题干；不包含答案/解析）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "知识点/关键词"},
                    "subject": {"type": "string", "description": "学科全名（可选，不填则用当前学科）", "default": ""},
                    "difficulty": {"type": "string", "description": "难度（简单/中等/困难）", "default": "中等"},
                    "limit": {"type": "integer", "description": "返回数量（5-30）", "default": 10},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="analyze_topic",
            description="分析知识点结构：讲解顺序、易错点、建议大纲（JSON）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "知识点/主题"},
                    "subject": {"type": "string", "description": "学科全名（可选）", "default": ""},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="generate_explanation",
            description="生成知识点讲解（Markdown）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "知识点/主题"},
                    "subject": {"type": "string", "description": "学科全名（可选）", "default": ""},
                    "knowledge": {"type": "object", "description": "可选：retrieve_knowledge 的返回结果"},
                    "analysis": {"type": "object", "description": "可选：analyze_topic 的返回结果"},
                },
                "required": ["topic"],
            },
        ),
        Tool(
            name="generate_solution",
            description="为单道题生成分步解答（Markdown）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "stem": {"type": "string", "description": "题干（纯文本/LaTeX均可）"},
                    "subject": {"type": "string", "description": "学科全名（可选）", "default": ""},
                    "topic": {"type": "string", "description": "可选：关联知识点", "default": ""},
                },
                "required": ["stem"],
            },
        ),
        Tool(
            name="review_content",
            description="审查自学资料 Markdown（JSON：passed/issues/suggestions）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "主题（可选）", "default": ""},
                    "markdown": {"type": "string", "description": "待审查的 Markdown 文本"},
                },
                "required": ["markdown"],
            },
        ),
        Tool(
            name="get_user_profile",
            description="获取用户画像（能力/偏好/历史）。",
            inputSchema={
                "type": "object",
                "properties": {"user_id": {"type": "string", "description": "用户ID"}},
                "required": ["user_id"],
            },
        ),
        Tool(
            name="update_user_profile",
            description="更新用户画像（写入 preferences 的浅合并）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "用户ID"},
                    "patch": {"type": "object", "description": "要写入的偏好/字段（浅合并到 preferences）"},
                },
                "required": ["user_id", "patch"],
            },
        ),
        Tool(
            name="compress_context",
            description="压缩上下文：对 messages 做摘要（返回 summary）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role": {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                        "description": "消息列表",
                        "default": [],
                    },
                    "target_chars": {
                        "type": "integer",
                        "description": "目标摘要长度（字符数，建议 200-800）",
                        "default": 220,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="web_search",
            description=(
                "【联网搜索】互联网搜索并返回结构化结果。\n"
                "- provider=auto 时优先 Exa（更适合“时兴/热点素材”检索，支持按发布日期筛选），无 Exa key 时回退 BigModel。\n"
                "- 需要配置 EXA_API_KEY 或 ZHIPU_API_KEY。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词/问题"},
                    "limit": {
                        "type": "integer",
                        "description": "返回结果数量（1-10）",
                        "default": 5,
                    },
                    "provider": {
                        "type": "string",
                        "enum": ["auto", "exa", "bigmodel"],
                        "description": "搜索提供方：auto(优先 exa) | exa | bigmodel",
                        "default": "auto",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["trending", "patterns"],
                        "description": "trending=时兴素材；patterns=真题规律（不按发布日期过滤）",
                        "default": "trending",
                    },
                    "recency_days": {
                        "type": "integer",
                        "description": "trending 模式下按发布日期近 N 天筛选（仅 exa 生效）",
                        "default": 180,
                    },
                    "model": {
                        "type": "string",
                        "description": "可选：指定 BigModel 模型名（默认读取 ZHIPU_MODEL）",
                        "default": "",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="python_scientific_compute",
            description=(
                "【Python 科学计算】执行受限 Python 代码做数学/数值计算。"
                "不要 import；可直接使用 math / cmath / statistics / fractions / decimal / np / sp(若可用)。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "待执行的 Python 计算代码"},
                    "purpose": {"type": "string", "description": "本次计算用途（可选）", "default": ""},
                    "timeout_seconds": {"type": "integer", "description": "超时秒数（1-15）", "default": 5},
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="zhihu_fetch",
            description=(
                "【知乎抓取】抓取知乎文章/回答/专栏列表并转为 Markdown（最佳努力）。\n"
                "支持：zhuanlan.zhihu.com/p/xxx、www.zhihu.com/question/.../answer/...、知乎专栏。\n"
                "部分内容可能需要登录态 Cookie；可通过参数 cookies 或环境变量 ZHIHU_COOKIES 提供。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "知乎链接（文章/回答/专栏）"},
                    "cookies": {
                        "type": "string",
                        "description": "可选：登录态 Cookie（优先级高于环境变量）",
                        "default": "",
                    },
                    "timeout_seconds": {"type": "integer", "description": "请求超时（5-60秒）", "default": 30},
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="diagnose_export",
            description="""【诊断工具】诊断导出到组卷网功能的问题。
检查项目：
1. 登录状态（.env文件中的用户ID、Cookie、CSRF Token）
2. Cookie有效性（是否过期）
3. bankId配置（Cookie中 vs 代码配置）
4. sync_baskets API测试
5. 返回详细的诊断报告和修复建议

当导出功能出现问题时调用此工具获取诊断信息。""",
            inputSchema={
                "type": "object",
                "properties": {
                    "test_question_id": {
                        "type": "string",
                        "description": "用于测试的题目ID（可选，默认使用70287）",
                        "default": "70287",
                    },
                },
                "required": [],
            },
        ),
    ]
