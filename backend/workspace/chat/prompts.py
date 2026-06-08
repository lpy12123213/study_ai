from __future__ import annotations

from typing import Dict

from backend.llm.prompts import create_default_prompt_registry

PLAN_TAG_OPEN = "<EXAM_PAPER_PLAN>"
PLAN_TAG_CLOSE = "</EXAM_PAPER_PLAN>"


_TOPIC_MAP: Dict[str, str] = {
    "高中数学": "函数",
    "高中语文": "古诗词鉴赏",
    "高中英语": "阅读理解",
    "高中物理": "力学",
    "高中化学": "化学反应",
    "高中生物": "细胞",
    "初中数学": "方程",
    "初中语文": "现代文阅读",
    "初中英语": "语法",
    "初中物理": "电学",
    "初中化学": "元素化合物",
    "初中生物": "生态系统",
    "小学数学": "四则运算",
    "小学语文": "阅读理解",
    "小学英语": "单词",
}


SYSTEM_PROMPT_TEMPLATE = create_default_prompt_registry().get("chat.paper_compose.system.v1").template


def get_system_prompt(subject: str) -> str:
    subj = (subject or "").strip() or "高中数学"
    topic = _TOPIC_MAP.get(subj, "相关知识点")
    return create_default_prompt_registry().render(
        "chat.paper_compose.system.v1",
        subject=subj,
        subject_topic=topic,
        plan_open=PLAN_TAG_OPEN,
        plan_close=PLAN_TAG_CLOSE,
    ).content
