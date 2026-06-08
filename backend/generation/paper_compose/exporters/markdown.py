
from __future__ import annotations


AI_SYNTHESIS_REVIEW_NOTE = "※ 本题答案由 AI 生成，请复核。"


def _is_ai_synthesis(q: dict) -> bool:
    return str(q.get("answer_source") or q.get("answerSource") or "").strip() == "ai_synthesis"


def _table_cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def render_paper_markdown(
    paper: dict,
    *,
    include_stem: bool = False,
    include_answer: bool = False,
    include_analysis: bool = False,
) -> str:
    name = str(paper.get("paper_name") or paper.get("name") or "试卷").strip()
    pid = paper.get("paper_id") or paper.get("id") or ""
    created = str(paper.get("created_at") or paper.get("createdAt") or "").strip()
    questions = paper.get("questions") if isinstance(paper.get("questions"), list) else []

    lines = [f"# {name}", ""]
    meta = []
    if pid:
        meta.append(f"> 试卷 ID：{pid}")
    if created:
        meta.append(f"> 创建时间：{created}")
    if meta:
        lines.extend(meta)
        lines.append("")

    lines.append("| 题号 | 题型 | 难度 | 知识点 | 题目ID | 来源 |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for q in questions:
        if not isinstance(q, dict):
            continue
        order = q.get("order") or q.get("question_order") or ""
        qtype = _table_cell(q.get("type") or q.get("question_type") or "")
        diff = _table_cell(q.get("difficulty") or "")
        kp = _table_cell(q.get("knowledge_point") or q.get("knowledgePoint") or "")
        qid = _table_cell(q.get("question_id") or q.get("questionId") or "")
        src = _table_cell(q.get("source_url") or q.get("sourceUrl") or "")
        lines.append(f"| {order} | {qtype} | {diff} | {kp} | {qid} | {src} |")

    if include_stem or include_answer or include_analysis:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("## 题目内容（本地快照）")
        lines.append("")

        for q in questions:
            if not isinstance(q, dict):
                continue
            qid = str(q.get("question_id") or q.get("questionId") or "").strip()
            order = q.get("order") or q.get("question_order") or ""
            lines.append(f"### {order}. {qid}")
            lines.append("")

            if include_stem:
                stem = str(q.get("stem") or "").strip()
                if stem:
                    lines.append("**题干：**")
                    lines.append("")
                    lines.append(stem)
                    lines.append("")

            if include_answer:
                ans = str(q.get("answer") or "").strip()
                if ans:
                    lines.append("**答案：**")
                    lines.append("")
                    lines.append(ans)
                    if _is_ai_synthesis(q):
                        lines.append("")
                        lines.append(f"> {AI_SYNTHESIS_REVIEW_NOTE}")
                    lines.append("")

            if include_analysis:
                ana = str(q.get("analysis") or "").strip()
                if ana:
                    lines.append("**解析：**")
                    lines.append("")
                    lines.append(ana)
                    lines.append("")

    return "\n".join(lines).rstrip() + "\n"
