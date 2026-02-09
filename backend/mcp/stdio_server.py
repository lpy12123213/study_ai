"""
MCP 服务 - 为 AI 提供题目搜索与组卷工具
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

if __package__ is None or __package__ == "":
    # Allow running as a script: `python backend/mcp/stdio_server.py`
    # NOTE: file lives under `backend/mcp/`, so we need repo root (2 levels up).
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from backend.agent.memory import MemoryStore
from backend.core.settings import (
    API_TIMEOUT,
    DEFAULT_SUBJECT,
    LESSON_PLAN_API_KEY,
    LESSON_PLAN_BASE_URL,
    LESSON_PLAN_MODEL,
    SUB_MODEL,
)
from backend.crawler.zujuan_crawler import ZujuanCrawler
from backend.mcp.sub_ai_selector import select_best_question
from backend.mcp.bigmodel_web_search import web_search_with_bigmodel_mcp
from backend.mcp.reviewer import review_questions_with_openrouter
from backend.subjects import (
    DEFAULT_DIFFICULTY,
    DIFFICULTY_LEVELS,
    EDU_LEVELS,
    SUBJECTS,
    get_all_subjects,
    get_subject_config,
    normalize_difficulty,
    resolve_subject,
)


def _extract_json_obj(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    if raw.startswith("```"):
        raw = raw.strip().strip("`").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


async def _call_llm_text(
    *,
    messages: List[Dict[str, str]],
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> str:
    if not LESSON_PLAN_API_KEY:
        return ""
    headers = {"Authorization": f"Bearer {LESSON_PLAN_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=float(API_TIMEOUT or 120)) as client:
        resp = await client.post(f"{LESSON_PLAN_BASE_URL.rstrip('/')}/chat/completions", headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
    try:
        return str(data["choices"][0]["message"]["content"] or "")
    except Exception:
        return ""


def _pick_questions(questions: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
    scored = []
    for q in questions:
        stem = str(q.get("stem") or "")
        if not stem or len(stem) < 8:
            continue
        penalty = stem.count("[图片:") * 50 + max(0, len(stem) - 500) // 20
        scored.append((penalty, q))
    scored.sort(key=lambda x: x[0])
    return [q for _, q in scored[: max(1, limit)]]


class ExamPaperMCPServer:
    def __init__(self):
        self.server = Server("exam-paper-assistant")
        self.crawler: Optional[ZujuanCrawler] = None
        self.current_subject = DEFAULT_SUBJECT  # 当前学科
        self._register_handlers()

    def _register_handlers(self):
        """注册 MCP 工具处理器"""

        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
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
                    description="【联网搜索】通过智谱 BigModel 的 MCP Broker（web-search）进行互联网搜索并返回结构化结果。需要在 .env 配置 ZHIPU_API_KEY。",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "搜索关键词/问题"},
                            "limit": {
                                "type": "integer",
                                "description": "返回结果数量（1-10）",
                                "default": 5,
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
                            "cookies": {"type": "string", "description": "可选：登录态 Cookie（优先级高于环境变量）", "default": ""},
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

        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> Sequence[TextContent]:
            """处理工具调用"""
            async def ensure_crawler_initialized() -> None:
                if self.crawler is None:
                    self.crawler = ZujuanCrawler(subject=self.current_subject)
                await self.crawler.initialize()

            try:
                if name == "search_questions_by_keyword":
                    await ensure_crawler_initialized()
                    edu_level = (arguments.get("edu_level") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    try:
                        resolved_subject = resolve_subject(
                            subject_input or self.current_subject,
                            edu_level=edu_level,
                            strict=True,
                        )
                        difficulty = normalize_difficulty(
                            arguments.get("difficulty") or DEFAULT_DIFFICULTY,
                            strict=True,
                        )
                    except ValueError as exc:
                        result = {
                            "success": False,
                            "error": str(exc),
                            "current_subject": self.current_subject,
                            "available_subjects": list(SUBJECTS.keys()),
                            "allowed_difficulties": sorted(DIFFICULTY_LEVELS),
                            "allowed_edu_levels": list(EDU_LEVELS.keys()),
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    if resolved_subject != self.current_subject:
                        self.current_subject = resolved_subject
                        self.crawler.set_subject(resolved_subject)

                    result = await self.crawler.search_by_keyword(
                        keyword=arguments["keyword"],
                        subject=resolved_subject,
                        edu_level=edu_level,
                        limit=arguments.get("limit", 10),
                        difficulty=difficulty,
                        question_type=arguments.get("question_type", ""),       
                        learn_grade=arguments.get("learn_grade", ""),
                        learn_grade_id=arguments.get("learn_grade_id", 0),
                        textbook_version=arguments.get("textbook_version", ""),
                        max_pages=arguments.get("max_pages", 2),
                        year=arguments.get("year", 0),
                        province=arguments.get("province", ""),
                        province_id=arguments.get("province_id", -1),
                        paper_type_id=arguments.get("paper_type_id", 0),        
                        term=arguments.get("term", 0),
                        order_by=arguments.get("order_by", 2),
                        source_contains=arguments.get("source_contains", ""),   
                        stem_contains=arguments.get("stem_contains", ""),       
                        knowledge_contains=arguments.get("knowledge_contains", ""),
                        exclude_elective=bool(arguments.get("exclude_elective", False)),
                        elective_mode=arguments.get("elective_mode", ""),
                        elective_keywords=arguments.get("elective_keywords"),
                        dedup_by_stem=bool(arguments.get("dedup_by_stem", False)),
                        min_quality_score=arguments.get("min_quality_score", 0),
                        with_quality=bool(arguments.get("with_quality", True)),
                        difficulty_value_min=arguments.get("difficulty_value_min"),
                        difficulty_value_max=arguments.get("difficulty_value_max"),
                        require_difficulty=True,
                        strict_subject=True,
                    )
                    # 添加当前学科信息和使用提示
                    result["current_subject"] = self.current_subject
                    result["applied_difficulty"] = difficulty
                    if edu_level:
                        result["applied_edu_level"] = edu_level
                    result["hint"] = "搜索结果已包含完整题目信息(题干、难度、知识点)，公式已转换为LaTeX"

                elif name == "search_questions_by_knowledge":
                    await ensure_crawler_initialized()
                    edu_level = (arguments.get("edu_level") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    try:
                        resolved_subject = resolve_subject(
                            subject_input or self.current_subject,
                            edu_level=edu_level,
                            strict=True,
                        )
                        difficulty = normalize_difficulty(
                            arguments.get("difficulty") or DEFAULT_DIFFICULTY,
                            strict=True,
                        )
                    except ValueError as exc:
                        result = {
                            "success": False,
                            "error": str(exc),
                            "current_subject": self.current_subject,
                            "available_subjects": list(SUBJECTS.keys()),
                            "allowed_difficulties": sorted(DIFFICULTY_LEVELS),
                            "allowed_edu_levels": list(EDU_LEVELS.keys()),
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    if resolved_subject != self.current_subject:
                        self.current_subject = resolved_subject
                        self.crawler.set_subject(resolved_subject)

                    result = await self.crawler.search_by_knowledge(
                        knowledge_point=arguments["knowledge_point"],
                        subject=resolved_subject,
                        edu_level=edu_level,
                        limit=arguments.get("limit", 10),
                        difficulty=difficulty,
                        question_type=arguments.get("question_type", ""),       
                        learn_grade=arguments.get("learn_grade", ""),
                        learn_grade_id=arguments.get("learn_grade_id", 0),
                        textbook_version=arguments.get("textbook_version", ""),
                        max_pages=arguments.get("max_pages", 2),
                        year=arguments.get("year", 0),
                        province=arguments.get("province", ""),
                        province_id=arguments.get("province_id", -1),
                        paper_type_id=arguments.get("paper_type_id", 0),        
                        term=arguments.get("term", 0),
                        order_by=arguments.get("order_by", 2),
                        source_contains=arguments.get("source_contains", ""),   
                        stem_contains=arguments.get("stem_contains", ""),       
                        knowledge_contains=arguments.get("knowledge_contains", ""),
                        exclude_elective=bool(arguments.get("exclude_elective", False)),
                        elective_mode=arguments.get("elective_mode", ""),
                        elective_keywords=arguments.get("elective_keywords"),
                        dedup_by_stem=bool(arguments.get("dedup_by_stem", False)),
                        min_quality_score=arguments.get("min_quality_score", 0),
                        with_quality=bool(arguments.get("with_quality", True)),
                        difficulty_value_min=arguments.get("difficulty_value_min"),
                        difficulty_value_max=arguments.get("difficulty_value_max"),
                        require_difficulty=True,
                        strict_subject=True,
                    )
                    # 添加当前学科信息和使用提示
                    result["current_subject"] = self.current_subject
                    result["applied_difficulty"] = difficulty
                    if edu_level:
                        result["applied_edu_level"] = edu_level
                    result["hint"] = "搜索结果已包含完整题目信息(题干、难度、知识点)，公式已转换为LaTeX"

                elif name == "filter_questions":
                    await ensure_crawler_initialized()
                    result = await self.crawler.filter_questions(
                        question_ids=arguments["question_ids"],
                        difficulty=arguments.get("difficulty", ""),
                        question_type=arguments.get("question_type", ""),
                        limit=arguments.get("limit", 10),
                    )

                elif name == "get_question_info":
                    await ensure_crawler_initialized()
                    result = await self.crawler.get_question_info(
                        question_id=arguments["question_id"]
                    )

                elif name == "create_paper":
                    from backend.database.models import save_paper

                    paper_id = await save_paper(
                        paper_name=arguments["paper_name"],
                        questions=arguments["question_ids"],
                    )
                    result = {
                        "success": True,
                        "paper_id": paper_id,
                        "message": f"试卷 '{arguments['paper_name']}' 创建成功",
                    }

                elif name == "get_question_details":
                    await ensure_crawler_initialized()
                    # 批量获取题目详情
                    question_ids = arguments["question_ids"][:10]  # 限制最多10个
                    details = await self.crawler.batch_get_question_details(question_ids)
                    result = details

                elif name == "select_best_question":
                    await ensure_crawler_initialized()
                    # 子AI选题功能
                    question_ids = arguments["question_ids"][:5]  # 限制最多5个候选
                    requirement = arguments["requirement"]

                    # 先获取题目详情
                    details_result = await self.crawler.batch_get_question_details(question_ids)
                    questions = details_result.get("questions", [])

                    if not questions:
                        result = {"success": False, "error": "无法获取候选题目详情"}
                    else:
                        # 调用子AI选择最佳题目
                        result = await select_best_question(
                            questions=questions,
                            requirement=requirement
                        )

                        # 添加说明信息
                        if result.get("success"):
                            result["message"] = f"子AI已从{len(questions)}道候选题目中选择了最符合要求的题目"

                elif name == "export_to_zujuan":
                    await ensure_crawler_initialized()
                    # 导出到组卷网题篮
                    question_ids = arguments["question_ids"]
                    paper_name = arguments.get("paper_name", "AI组卷")
                    export_subject = (arguments.get("subject") or "").strip()

                    if export_subject:
                        # 复用 set_subject 的模糊匹配逻辑
                        if export_subject not in SUBJECTS:
                            matched = None
                            for name_key in SUBJECTS.keys():
                                if export_subject in name_key or name_key in export_subject:
                                    matched = name_key
                                    break
                            if matched:
                                export_subject = matched
                            else:
                                result = {
                                    "success": False,
                                    "error": f"未找到学科: {export_subject}",
                                    "available_subjects": list(SUBJECTS.keys()),
                                    "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文",
                                }
                                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                        self.current_subject = export_subject
                        if self.crawler is not None:
                            self.crawler.set_subject(export_subject)

                    # 先获取题目详情（用于填充题型、难度等信息）
                    details_result = await self.crawler.batch_get_question_details(
                        question_ids[:10]  # 限制最多10个
                    )
                    question_details = details_result.get("questions", [])

                    # 调用导出功能（MCP环境无法弹出GUI，禁用自动登录）
                    result = await self.crawler.export_to_basket(
                        question_ids=question_ids,
                        question_details=question_details,
                        auto_login=False  # MCP环境不支持GUI弹窗
                    )

                    # 如果 cookie 过期，显示友好提示
                    if result.get("cookie_expired"):
                        result["user_action_required"] = True
                        result["message"] = "Cookie 已过期，请按以下步骤重新登录"

                    # 如果需要登录（首次使用），尝试启动独立登录窗口
                    elif result.get("login_required"):
                        # 启动独立进程显示登录窗口
                        login_result = await self.crawler.login_via_subprocess()
                        result["login_window"] = login_result
                        result["login_instructions"] = [
                            "首次使用需要登录组卷网：",
                            f"1. 双击运行 scripts/登录组卷网.bat \"{self.current_subject}\"",
                            "2. 在弹出的浏览器中登录",
                            "3. 登录成功后按回车保存",
                            "4. 重新调用此工具导出题目"
                        ]

                    # 如果成功，添加额外提示
                    if result.get("success"):
                        result["next_steps"] = [
                            "1. 打开组卷网题篮页面: https://zujuan.xkw.com/basket/",
                            "2. 检查题目是否已添加",
                            "3. 点击'生成试卷'按钮完成组卷"
                        ]

                elif name == "review_paper":
                    await ensure_crawler_initialized()

                    # 可选切换学科
                    target_subject = (arguments.get("subject") or "").strip()
                    if target_subject:
                        if target_subject not in SUBJECTS:
                            matched = None
                            for name_key in SUBJECTS.keys():
                                if target_subject in name_key or name_key in target_subject:
                                    matched = name_key
                                    break
                            if matched:
                                target_subject = matched
                            else:
                                result = {
                                    "success": False,
                                    "error": f"未找到学科: {target_subject}",
                                    "available_subjects": list(SUBJECTS.keys()),
                                    "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文",
                                }
                                return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                        self.current_subject = target_subject
                        self.crawler.set_subject(target_subject)

                    paper_id = arguments.get("paper_id")
                    question_ids = arguments.get("question_ids") or []
                    paper_name = (arguments.get("paper_name") or "").strip()
                    focus = (arguments.get("focus") or "").strip()
                    strictness = int(arguments.get("strictness", 3) or 3)
                    max_questions = int(arguments.get("max_questions", 20) or 20)
                    if max_questions < 1:
                        max_questions = 1
                    if max_questions > 50:
                        max_questions = 50

                    paper_meta = None
                    if paper_id is not None:
                        from backend.database.models import get_paper

                        paper = await get_paper(int(paper_id))
                        if not paper:
                            result = {"success": False, "error": f"未找到试卷 paper_id={paper_id}"}
                            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                        paper_meta = paper
                        if not paper_name:
                            paper_name = paper.get("paper_name", "") or ""
                        question_ids = [q.get("question_id") for q in paper.get("questions", []) if q.get("question_id")]

                    if not question_ids:
                        result = {
                            "success": False,
                            "error": "review_paper 需要 paper_id 或 question_ids",
                            "hint": "传入 paper_id（create_paper 的返回）或直接传入题目ID列表",
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    question_ids = [str(x) for x in question_ids][:max_questions]

                    # 拉取题干等信息（batch_get_question_details 单次最多10个，这里分批拉取）
                    details_all = []
                    for i in range(0, len(question_ids), 10):
                        chunk = question_ids[i : i + 10]
                        chunk_res = await self.crawler.batch_get_question_details(chunk)
                        details_all.extend(chunk_res.get("questions", []))

                    # 保持顺序
                    detail_map = {str(q.get("question_id")): q for q in details_all if q.get("question_id")}
                    ordered_questions = [detail_map.get(qid, {"question_id": qid}) for qid in question_ids]

                    result = await review_questions_with_openrouter(
                        questions=ordered_questions,
                        paper_name=paper_name,
                        subject=self.current_subject,
                        focus=focus,
                        strictness=strictness,
                    )
                    if paper_meta:
                        result["paper_meta"] = {
                            "paper_id": paper_meta.get("paper_id"),
                            "paper_name": paper_meta.get("paper_name"),
                            "question_count": len(paper_meta.get("questions", []) or []),
                        }

                elif name == "list_subjects":
                    # 列出所有支持的学科
                    edu_level = arguments.get("edu_level", "")
                    subjects = get_all_subjects()

                    if edu_level:
                        # 按学段筛选
                        subjects = [s for s in subjects if s["name"].startswith(edu_level)]

                    result = {
                        "success": True,
                        "current_subject": self.current_subject,
                        "subjects": subjects,
                        "count": len(subjects),
                        "edu_levels": ["小学", "初中", "高中"]
                    }

                elif name == "set_subject":
                    # 切换学科
                    subject = arguments["subject"]

                    if subject not in SUBJECTS:
                        # 尝试模糊匹配
                        matched = None
                        for name_key in SUBJECTS.keys():
                            if subject in name_key or name_key in subject:
                                matched = name_key
                                break

                        if matched:
                            subject = matched
                        else:
                            result = {
                                "success": False,
                                "error": f"未找到学科: {subject}",
                                "available_subjects": list(SUBJECTS.keys()),
                                "hint": "请使用完整学科名，如：高中数学、初中物理、小学语文"
                            }
                            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    # 切换学科
                    self.current_subject = subject
                    if self.crawler is not None:
                        self.crawler.set_subject(subject)
                    config = get_subject_config(subject)

                    result = {
                        "success": True,
                        "message": f"已切换到 {subject}",
                        "current_subject": subject,
                        "bank_id": config["bank_id"],
                        "edu_id": config["edu_id"]
                    }

                elif name == "get_current_subject":
                    # 获取当前学科
                    config = get_subject_config(self.current_subject)     
                    result = {
                        "success": True,
                        "current_subject": self.current_subject,
                        "short_name": config.get("short_name", ""),       
                        "bank_id": config["bank_id"],
                        "edu_id": config["edu_id"]
                    }

                elif name == "get_available_filters":
                    await ensure_crawler_initialized()
                    edu_level = (arguments.get("edu_level") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    try:
                        resolved_subject = resolve_subject(
                            subject_input or self.current_subject,
                            edu_level=edu_level,
                            strict=True,
                        )
                    except ValueError as exc:
                        result = {
                            "success": False,
                            "error": str(exc),
                            "current_subject": self.current_subject,
                            "available_subjects": list(SUBJECTS.keys()),
                            "allowed_edu_levels": list(EDU_LEVELS.keys()),
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    if resolved_subject != self.current_subject:
                        self.current_subject = resolved_subject
                        self.crawler.set_subject(resolved_subject)

                    result = await self.crawler.get_available_filters()
                    result["current_subject"] = self.current_subject

                elif name == "compose_paper_blueprint":
                    await ensure_crawler_initialized()
                    edu_level = (arguments.get("edu_level") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    try:
                        resolved_subject = resolve_subject(
                            subject_input or self.current_subject,
                            edu_level=edu_level,
                            strict=True,
                        )
                    except ValueError as exc:
                        result = {
                            "success": False,
                            "error": str(exc),
                            "current_subject": self.current_subject,
                            "available_subjects": list(SUBJECTS.keys()),
                            "allowed_edu_levels": list(EDU_LEVELS.keys()),
                        }
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

                    if resolved_subject != self.current_subject:
                        self.current_subject = resolved_subject
                        self.crawler.set_subject(resolved_subject)

                    result = await self.crawler.compose_paper_blueprint(
                        blueprint=arguments.get("blueprint") or [],
                        subject=resolved_subject,
                        edu_level=edu_level,
                        learn_grade=arguments.get("learn_grade", ""),
                        learn_grade_id=arguments.get("learn_grade_id", 0),
                        textbook_version=arguments.get("textbook_version", ""),
                        elective_mode=arguments.get("elective_mode", ""),
                        elective_keywords=arguments.get("elective_keywords"),
                        exclude_elective=bool(arguments.get("exclude_elective", False)),
                        year=arguments.get("year", 0),
                        province=arguments.get("province", ""),
                        province_id=arguments.get("province_id", -1),
                        paper_type_id=arguments.get("paper_type_id", 0),
                        term=arguments.get("term", 0),
                        order_by=arguments.get("order_by", 2),
                        max_pages=arguments.get("max_pages", 2),
                        per_slot_expand=arguments.get("per_slot_expand", 3),
                        min_quality_score=arguments.get("min_quality_score", 0),
                        dedup_by_stem=bool(arguments.get("dedup_by_stem", True)),
                        strict_subject=bool(arguments.get("strict_subject", True)),
                    )
                    result["current_subject"] = self.current_subject

                elif name == "retrieve_knowledge":
                    topic = (arguments.get("topic") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    difficulty = (arguments.get("difficulty") or DEFAULT_DIFFICULTY).strip() or DEFAULT_DIFFICULTY
                    if not topic:
                        result = {"success": False, "error": "missing_topic"}
                    elif not LESSON_PLAN_API_KEY:
                        result = {
                            "success": True,
                            "topic": topic,
                            "subject": subject_input or self.current_subject,
                            "difficulty": difficulty,
                            "definition": "",
                            "key_points": [],
                            "prerequisites": [],
                            "common_mistakes": [],
                            "methods": [],
                            "source": "fallback",
                            "note": "未配置 LESSON_PLAN_API_KEY，返回为空。",
                        }
                    else:
                        prompt = f"""请为“{subject_input or self.current_subject}”的知识点“{topic}”生成事实性要点。\n\n要求：\n- 输出严格 JSON（不要 Markdown、不要代码块）\n- 字段：definition(str), key_points(str[]), prerequisites(str[]), common_mistakes(str[]), methods(str[])\n- 难度参考：{difficulty}\n"""
                        text = await _call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的学科老师，输出必须是JSON。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=SUB_MODEL,
                            temperature=0.2,
                            max_tokens=900,
                        )
                        obj = _extract_json_obj(text)
                        result = {
                            "success": True,
                            "topic": topic,
                            "subject": subject_input or self.current_subject,
                            "difficulty": difficulty,
                            "definition": str(obj.get("definition") or ""),
                            "key_points": list(obj.get("key_points") or []),
                            "prerequisites": list(obj.get("prerequisites") or []),
                            "common_mistakes": list(obj.get("common_mistakes") or []),
                            "methods": list(obj.get("methods") or []),
                            "source": "llm",
                        }

                elif name == "search_examples":
                    await ensure_crawler_initialized()
                    topic = (arguments.get("topic") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    difficulty_input = (arguments.get("difficulty") or DEFAULT_DIFFICULTY).strip()
                    limit = int(arguments.get("limit", 3) or 3)
                    limit = max(1, min(5, limit))
                    try:
                        resolved_subject = resolve_subject(subject_input or self.current_subject, strict=True)
                        difficulty = normalize_difficulty(difficulty_input or DEFAULT_DIFFICULTY, strict=True)
                    except ValueError as exc:
                        result = {"success": False, "error": str(exc)}
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
                    if resolved_subject != self.current_subject:
                        self.current_subject = resolved_subject
                        self.crawler.set_subject(resolved_subject)
                    res = await self.crawler.search_by_keyword(
                        keyword=topic,
                        subject=resolved_subject,
                        limit=max(12, limit * 4),
                        difficulty=difficulty,
                        max_pages=2,
                        dedup_by_stem=True,
                        min_quality_score=10,
                        with_quality=True,
                        require_difficulty=True,
                        strict_subject=True,
                    )
                    questions = list(res.get("questions") or [])
                    result = {
                        "success": True,
                        "topic": topic,
                        "subject": resolved_subject,
                        "difficulty": difficulty,
                        "examples": _pick_questions(questions, limit=limit),
                    }

                elif name == "search_exercises":
                    await ensure_crawler_initialized()
                    topic = (arguments.get("topic") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    difficulty_input = (arguments.get("difficulty") or DEFAULT_DIFFICULTY).strip()
                    limit = int(arguments.get("limit", 10) or 10)
                    limit = max(5, min(30, limit))
                    try:
                        resolved_subject = resolve_subject(subject_input or self.current_subject, strict=True)
                        difficulty = normalize_difficulty(difficulty_input or DEFAULT_DIFFICULTY, strict=True)
                    except ValueError as exc:
                        result = {"success": False, "error": str(exc)}
                        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
                    if resolved_subject != self.current_subject:
                        self.current_subject = resolved_subject
                        self.crawler.set_subject(resolved_subject)
                    res = await self.crawler.search_by_keyword(
                        keyword=topic,
                        subject=resolved_subject,
                        limit=max(20, limit * 3),
                        difficulty=difficulty,
                        max_pages=2,
                        dedup_by_stem=True,
                        min_quality_score=10,
                        with_quality=True,
                        require_difficulty=True,
                        strict_subject=True,
                    )
                    questions = list(res.get("questions") or [])
                    result = {
                        "success": True,
                        "topic": topic,
                        "subject": resolved_subject,
                        "difficulty": difficulty,
                        "exercises": _pick_questions(questions, limit=limit),
                    }

                elif name == "analyze_topic":
                    topic = (arguments.get("topic") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    if not LESSON_PLAN_API_KEY:
                        result = {
                            "success": True,
                            "topic": topic,
                            "subject": subject_input,
                            "outline": ["概念与定义", "方法小结", "例题精讲", "分层练习"],
                            "confusions": [],
                            "source": "fallback",
                        }
                    else:
                        payload = {
                            "topic": topic,
                            "subject": subject_input or self.current_subject,
                            "required_output": {
                                "outline": "string[]",
                                "confusions": "string[]",
                                "teaching_order": "string[]",
                            },
                        }
                        text = await _call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的教学设计专家，输出必须是JSON。"},
                                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                            ],
                            model=LESSON_PLAN_MODEL,
                            temperature=0.2,
                            max_tokens=900,
                        )
                        obj = _extract_json_obj(text)
                        result = {
                            "success": True,
                            "topic": topic,
                            "subject": subject_input or self.current_subject,
                            "outline": list(obj.get("outline") or []),
                            "confusions": list(obj.get("confusions") or []),
                            "teaching_order": list(obj.get("teaching_order") or []),
                            "source": "llm",
                        }

                elif name == "generate_explanation":
                    topic = (arguments.get("topic") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    knowledge = arguments.get("knowledge") if isinstance(arguments.get("knowledge"), dict) else {}
                    analysis = arguments.get("analysis") if isinstance(arguments.get("analysis"), dict) else {}
                    if not LESSON_PLAN_API_KEY:
                        result = {
                            "success": True,
                            "markdown": f"## 一、知识点讲解：{topic}\n\n（未配置模型，无法生成详细讲解。）\n",
                            "source": "fallback",
                        }
                    else:
                        prompt = {
                            "topic": topic,
                            "subject": subject_input or self.current_subject,
                            "knowledge": knowledge,
                            "analysis": analysis,
                            "instructions": "请生成 Markdown 章节：知识点讲解。包含：定义、关键点、常见误区、方法小结。不要输出练习题。",
                        }
                        text = await _call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的自学资料编写老师，输出必须是Markdown。"},
                                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                            ],
                            model=LESSON_PLAN_MODEL,
                            temperature=0.4,
                            max_tokens=1500,
                        )
                        result = {"success": True, "markdown": (text or "").strip(), "source": "llm"}

                elif name == "generate_solution":
                    stem = (arguments.get("stem") or "").strip()
                    subject_input = (arguments.get("subject") or "").strip()
                    topic = (arguments.get("topic") or "").strip()
                    if not LESSON_PLAN_API_KEY:
                        result = {"success": True, "markdown": "（未配置模型，无法生成解答。）", "source": "fallback"}
                    else:
                        prompt = f"""请为下面题目写出详细分步解答（Markdown）。\n\n要求：\n- 每一步说明在做什么\n- 如果题干信息不足，请说明需要补充什么\n\n学科：{subject_input or self.current_subject}\n知识点：{topic or '（未指定）'}\n\n题目：\n{stem}\n"""
                        text = await _call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的解题老师，输出必须是Markdown。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=LESSON_PLAN_MODEL,
                            temperature=0.3,
                            max_tokens=1200,
                        )
                        result = {"success": True, "markdown": (text or "").strip(), "source": "llm"}

                elif name == "review_content":
                    topic = (arguments.get("topic") or "").strip()
                    markdown = (arguments.get("markdown") or "").strip()
                    if not markdown:
                        result = {"success": False, "error": "missing_markdown"}
                    elif not LESSON_PLAN_API_KEY:
                        result = {"success": True, "passed": True, "issues": [], "suggestions": [], "source": "fallback"}
                    else:
                        prompt = f"""请审查下面这份自学资料 Markdown，找出：\n1) 逻辑跳跃/不清晰处\n2) 可能的错误或表述不严谨\n3) 建议改进点（最多5条）\n\n要求：输出严格 JSON（不要 Markdown）。字段：passed(bool), issues(string[]), suggestions(string[])\n\n主题：{topic}\n\nMarkdown:\n{markdown}\n"""
                        text = await _call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是严谨的审稿人，输出必须是JSON。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=LESSON_PLAN_MODEL,
                            temperature=0.1,
                            max_tokens=900,
                        )
                        obj = _extract_json_obj(text)
                        result = {
                            "success": True,
                            "passed": bool(obj.get("passed")) if "passed" in obj else True,
                            "issues": list(obj.get("issues") or []),
                            "suggestions": list(obj.get("suggestions") or []),
                            "source": "llm",
                        }

                elif name == "get_user_profile":
                    user_id = (arguments.get("user_id") or "").strip()
                    store = MemoryStore()
                    profile = await store.get_user_profile(user_id=user_id or "anonymous")
                    result = {"success": True, "profile": profile.to_dict()}

                elif name == "update_user_profile":
                    user_id = (arguments.get("user_id") or "").strip()
                    patch = arguments.get("patch") if isinstance(arguments.get("patch"), dict) else {}
                    store = MemoryStore()
                    profile = await store.update_user_profile(user_id=user_id or "anonymous", patch=patch)
                    result = {"success": True, "profile": profile.to_dict()}

                elif name == "compress_context":
                    messages = arguments.get("messages") if isinstance(arguments.get("messages"), list) else []
                    target_chars = int(arguments.get("target_chars", 220) or 220)
                    target_chars = max(80, min(2000, target_chars))
                    if not messages:
                        result = {"success": True, "summary": ""}
                    elif not LESSON_PLAN_API_KEY:
                        parts = []
                        for m in messages[-6:]:
                            role = str((m or {}).get("role") or "unknown")
                            content = str((m or {}).get("content") or "")[:120]
                            if content:
                                parts.append(f"{role}: {content}")
                        summary = " | ".join(parts)[:target_chars]
                        result = {"success": True, "summary": summary, "source": "fallback"}
                    else:
                        prompt = f"""请将下面的对话/记录压缩为一段简洁摘要（约{target_chars}字左右），保留：\n- 用户主要目标与约束\n- 关键决策\n- 重要工具结果/错误\n\n输出：纯文本摘要（不要Markdown）。\n\n记录：\n{json.dumps(messages, ensure_ascii=False)}\n"""
                        text = await _call_llm_text(
                            messages=[
                                {"role": "system", "content": "你是上下文压缩器，输出必须是纯文本摘要。"},
                                {"role": "user", "content": prompt},
                            ],
                            model=SUB_MODEL,
                            temperature=0.2,
                            max_tokens=400,
                        )
                        result = {"success": True, "summary": (text or "").strip(), "source": "llm"}

                elif name == "web_search":
                    query = (arguments.get("query") or "").strip()        
                    limit = arguments.get("limit", 5)
                    model = (arguments.get("model") or "").strip()        
                    result = await web_search_with_bigmodel_mcp(
                        query=query,
                        limit=limit,
                        model=model,
                    )

                elif name == "zhihu_fetch":
                    url = (arguments.get("url") or "").strip()
                    cookies = (arguments.get("cookies") or "").strip() or (os.getenv("ZHIHU_COOKIES") or "").strip()
                    timeout_seconds = int(arguments.get("timeout_seconds") or 30)
                    timeout_seconds = max(5, min(timeout_seconds, 60))

                    if not url:
                        result = {"success": False, "error": "url 不能为空"}
                    else:
                        try:
                            from backend.mcp.zhihu_fetcher import ZhihuFetcher

                            fetcher = ZhihuFetcher(cookies=cookies, timeout_seconds=timeout_seconds)
                            res = await fetcher.fetch(url, cookies=cookies)
                            result = res.to_dict()
                            if result.get("success") is False and result.get("error") == "cookies_required" and not cookies:
                                result["note"] = "需要登录态：请在环境变量或 .env 配置 ZHIHU_COOKIES，或通过参数 cookies 传入"
                        except Exception as exc:
                            result = {"success": False, "error": f"zhihu_fetch failed: {exc}"}

                elif name == "diagnose_export":
                    # 诊断导出功能
                    result = await self._diagnose_export(
                        test_question_id=arguments.get("test_question_id", "70287")
                    )

                else:
                    result = {"error": f"未知工具: {name}"}

                return [
                    TextContent(
                        type="text",
                        text=json.dumps(result, ensure_ascii=False, indent=2),
                    )
                ]

            except Exception as e:
                return [
                    TextContent(
                        type="text",
                        text=json.dumps({"error": str(e), "tool": name}, ensure_ascii=False),
                    )
                ]

    async def run(self):
        """启动 MCP 服务器（stdio）"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options(),
            )

    async def _diagnose_export(self, test_question_id: str = "70287") -> dict:
        """诊断导出功能"""
        import httpx
        import time

        diagnosis = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "checks": [],
            "issues": [],
            "recommendations": [],
            "raw_data": {}
        }

        # 1. 检查 .env 文件
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        env_check = {"name": "ENV文件检查", "status": "unknown", "details": {}}

        if os.path.exists(env_file):
            env_check["status"] = "exists"
            try:
                env_data = {}
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, value = line.split("=", 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        env_data[key] = value

                user_id = env_data.get("ZUJUAN_USER_ID", "")
                csrf_token = env_data.get("ZUJUAN_CSRF_TOKEN", "")
                cookies = env_data.get("ZUJUAN_COOKIES", "")

                env_check["details"] = {
                    "user_id": user_id if user_id else "❌ 未设置",
                    "csrf_token_length": len(csrf_token) if csrf_token else 0,
                    "cookies_length": len(cookies) if cookies else 0,
                    "has_user_id_in_cookie": "userId=" in cookies,
                }

                if not user_id:
                    diagnosis["issues"].append("❌ .env中未找到ZUJUAN_USER_ID，表示未登录")
                    env_check["status"] = "missing_user_id"
                elif not cookies:
                    diagnosis["issues"].append("❌ .env中未找到ZUJUAN_COOKIES")
                    env_check["status"] = "missing_cookies"
                else:
                    env_check["status"] = "ok"

            except Exception as e:
                env_check["status"] = "error"
                env_check["error"] = str(e)
                diagnosis["issues"].append(f"❌ 读取.env文件失败: {e}")
        else:
            env_check["status"] = "not_found"
            diagnosis["issues"].append("❌ .env文件不存在")

        diagnosis["checks"].append(env_check)

        # 2. 检查Cookie中的bankId
        bank_id_check = {"name": "BankID检查", "status": "unknown", "details": {}}

        if "cookies" in locals() and cookies:
            cookie_bank_id = None
            for part in cookies.split(";"):
                part = part.strip()
                if part.startswith("bankId="):
                    cookie_bank_id = part.split("=", 1)[1].strip()
                    break

            config_bank_id = str(self.crawler.bank_id) if self.crawler else "11"

            # 查找bankId对应的学科名称
            cookie_subject = "未知"
            config_subject = self.current_subject
            for subj_name, subj_config in SUBJECTS.items():
                if str(subj_config["bank_id"]) == cookie_bank_id:
                    cookie_subject = subj_name
                    break

            bank_id_check["details"] = {
                "cookie_bank_id": cookie_bank_id or "❌ 未找到",
                "cookie_subject": cookie_subject,
                "config_bank_id": config_bank_id,
                "config_subject": config_subject,
                "match": cookie_bank_id == config_bank_id if cookie_bank_id else False
            }

            if not cookie_bank_id:
                diagnosis["issues"].append("⚠️ Cookie中未找到bankId")
                bank_id_check["status"] = "missing"
            elif cookie_bank_id != config_bank_id:
                diagnosis["issues"].append(f"⚠️ BankID不匹配: Cookie中是{cookie_subject}(bankId={cookie_bank_id}), 当前配置是{config_subject}(bankId={config_bank_id})")
                bank_id_check["status"] = "mismatch"
                bank_id_check["note"] = f"当前登录态题库为 {cookie_subject}，导出目标为 {config_subject}"
                diagnosis["recommendations"].append(f"💡 请先切换到“{config_subject}”并重新登录保存Cookie，再执行导出")
            else:
                bank_id_check["status"] = "ok"
        else:
            bank_id_check["status"] = "no_cookies"

        diagnosis["checks"].append(bank_id_check)

        # 3. 测试API连通性
        api_check = {"name": "API连通性测试", "status": "unknown", "details": {}}

        if "cookies" in locals() and cookies and "csrf_token" in locals():
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Cookie": cookies,
                        "Accept": "application/json",
                        "Origin": "https://zujuan.xkw.com",
                        "Referer": "https://zujuan.xkw.com/",
                        "RequestVerification": csrf_token,
                    }

                    # 使用cookie中的bankId（如果存在）
                    test_bank_id = cookie_bank_id if "cookie_bank_id" in locals() and cookie_bank_id else (config_bank_id or "11")

                    # 先测试空篮子同步
                    resp = await client.post(
                        "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                        data={
                            "bankId": test_bank_id,
                            "syncFlag": "9",
                            "basketJson": "[]"
                        },
                        headers=headers
                    )

                    api_check["details"]["empty_sync"] = {
                        "status_code": resp.status_code,
                        "bank_id_used": test_bank_id,
                    }

                    if resp.status_code == 200:
                        try:
                            data = resp.json()
                            api_check["details"]["empty_sync"]["response"] = {
                                "serverVersion": data.get("serverVersion"),
                                "questions_count": len(data.get("questions", []))
                            }
                            diagnosis["raw_data"]["empty_sync_response"] = data
                        except:
                            api_check["details"]["empty_sync"]["response_text"] = resp.text[:200]

                    # 再测试添加题目
                    import time as time_module
                    current_time = int(time_module.time() * 1000)
                    test_basket = [{
                        "questionId": int(test_question_id),
                        "addTime": current_time,
                        "childNum": 1,
                        "quesDiff": 3,
                        "quesTypeId": 2703,
                        "quesTypeName": "填空题",
                        "status": "CHECK",
                    }]

                    resp2 = await client.post(
                        "https://zujuan.xkw.com/zujuan-api/sync_baskets",
                        data={
                            "bankId": test_bank_id,
                            "syncFlag": "9",
                            "basketJson": json.dumps(test_basket, ensure_ascii=False)
                        },
                        headers=headers
                    )

                    api_check["details"]["add_question"] = {
                        "status_code": resp2.status_code,
                        "test_question_id": test_question_id,
                        "bank_id_used": test_bank_id,
                    }

                    if resp2.status_code == 200:
                        try:
                            data2 = resp2.json()
                            server_version = data2.get("serverVersion")
                            questions = data2.get("questions", [])

                            api_check["details"]["add_question"]["response"] = {
                                "serverVersion": server_version,
                                "questions_count": len(questions),
                                "question_ids_returned": [q.get("questionId") for q in questions[:5]]
                            }
                            diagnosis["raw_data"]["add_question_response"] = data2

                            # 检查题目是否成功添加
                            test_qid = int(test_question_id)
                            question_added = any(q.get("questionId") == test_qid for q in questions)

                            if question_added:
                                api_check["status"] = "ok"
                                api_check["details"]["add_question"]["question_added"] = True
                            else:
                                api_check["status"] = "question_not_in_response"
                                api_check["details"]["add_question"]["question_added"] = False
                                diagnosis["issues"].append(f"⚠️ 题目{test_question_id}未出现在响应的questions中")

                        except Exception as e:
                            api_check["details"]["add_question"]["parse_error"] = str(e)
                            api_check["details"]["add_question"]["response_text"] = resp2.text[:200]
                    else:
                        api_check["status"] = "http_error"
                        diagnosis["issues"].append(f"❌ API返回HTTP {resp2.status_code}")

            except Exception as e:
                api_check["status"] = "error"
                api_check["error"] = str(e)
                diagnosis["issues"].append(f"❌ API测试失败: {e}")
        else:
            api_check["status"] = "skipped"
            api_check["reason"] = "缺少cookies或csrf_token"

        diagnosis["checks"].append(api_check)

        # 4. 生成建议
        if not diagnosis["issues"]:
            diagnosis["overall_status"] = "✅ 所有检查通过"
            diagnosis["recommendations"].append("导出功能应该正常工作，如果仍有问题请检查网络连接")
        else:
            diagnosis["overall_status"] = f"⚠️ 发现 {len(diagnosis['issues'])} 个问题"

            if any("未登录" in issue or "ZUJUAN_USER_ID" in issue for issue in diagnosis["issues"]):
                diagnosis["recommendations"].append(f"🔧 请运行 scripts/登录组卷网.bat \"{self.current_subject}\" 进行登录")

            if any("BankID不匹配" in issue for issue in diagnosis["issues"]):
                diagnosis["recommendations"].append("🔧 如需导出到其他学科题篮，请在浏览器中切换到目标学科后重新登录保存Cookie")
                diagnosis["recommendations"].append(f"🔧 例如：访问 https://zujuan.xkw.com/ 并切换到“{self.current_subject}”后重新运行登录脚本")

            if any("API" in issue or "HTTP" in issue for issue in diagnosis["issues"]):
                diagnosis["recommendations"].append("🔧 检查网络连接，或尝试重新登录获取新的Cookie")

        # 添加调试信息
        diagnosis["debug_info"] = {
            "current_subject": self.current_subject,
            "crawler_bank_id": self.crawler.bank_id if self.crawler else None,
            "test_question_id": test_question_id,
        }

        return diagnosis


async def main():
    server = ExamPaperMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
