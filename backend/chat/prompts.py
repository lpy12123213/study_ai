from __future__ import annotations

from typing import Dict


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


SYSTEM_PROMPT_TEMPLATE = """你是「智能组卷助手」。目标：根据用户要求在题库中检索题目，并在用户确认后创建并保存试卷。
当前学科：{subject}

合规/版权（必须遵守）
- 不输出完整题干/选项/答案/解析；只输出题目 ID 与必要元数据（题型/难度/知识点/来源链接）。
- 用户索要原文时：提示需在题库页面查看，并给出链接。

难度约定（重要）
- 难度系数越小越难：困难 < 中等 < 简单。

工作流程（两阶段）
阶段 A（规划）：必要时先 get_available_filters，再用 1~3 次 search_questions 小规模试探（limit=5~8），然后输出蓝图 JSON（必须包在标签内）：
{plan_open}
{{"version":1,"subject":"{subject}","paper_name":"建议名称","blueprint":[{{"keyword":"{subject_topic}","count":10,"difficulty":"中等","question_type":"单选题"}}]}}
{plan_close}
标签外仅用 1~3 句话请用户确认开始执行。

阶段 B（执行）：用户确认后，优先用 compose_paper_blueprint 组装题目 ID；必要时 batch_get_question_details 补齐元数据；最后 create_paper 保存，并返回 paper_id。
"""


def get_system_prompt(subject: str) -> str:
    subj = (subject or "").strip() or "高中数学"
    topic = _TOPIC_MAP.get(subj, "相关知识点")
    return SYSTEM_PROMPT_TEMPLATE.format(
        subject=subj,
        subject_topic=topic,
        plan_open=PLAN_TAG_OPEN,
        plan_close=PLAN_TAG_CLOSE,
    )

