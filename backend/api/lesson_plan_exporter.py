"""Lesson plan export utilities."""

from __future__ import annotations

from typing import Any, Dict


def export_to_markdown(plan: Dict[str, Any]) -> str:
    """Export lesson plan to Markdown format."""
    lines = [
        f"# {plan.get('title', 'Untitled Lesson')}",
        "",
        "## Lesson Information",
        "",
        f"- **Subject:** {plan.get('subject', 'N/A')}",
        f"- **Grade:** {plan.get('grade', 'N/A')}",
        f"- **Topic:** {plan.get('topic', 'N/A')}",
        f"- **Duration:** {plan.get('duration_minutes', 45)} minutes",
        "",
        "## Learning Objectives",
        "",
    ]

    for obj in plan.get("objectives", []):
        if isinstance(obj, dict):
            lines.append(f"- {obj.get('description', '')}")
        else:
            lines.append(f"- {obj}")

    lines.extend(["", "## Lesson Sections", ""])

    for section in plan.get("sections", []):
        title = section.get("title", "Untitled Section")
        duration = section.get("duration_minutes", 0)
        lines.append(f"### {title} ({duration} min)")
        lines.append("")
        lines.append(section.get("content", ""))
        lines.append("")

        activities = section.get("activities", [])
        if activities:
            lines.append("**Activities:**")
            for activity in activities:
                lines.append(f"- {activity}")
            lines.append("")

        resources = section.get("resources", [])
        if resources:
            lines.append("**Resources:**")
            for resource in resources:
                lines.append(f"- {resource}")
            lines.append("")

    summary = plan.get("summary")
    if summary:
        lines.extend(["## Summary", "", summary, ""])

    return "\n".join(lines)


def export_to_html(plan: Dict[str, Any]) -> str:
    """Export lesson plan to HTML format."""
    md_content = export_to_markdown(plan)

    # Simple Markdown to HTML conversion
    html_lines = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>{plan.get('title', 'Lesson Plan')}</title>",
        "<style>",
        "body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
        "h1 { color: #333; }",
        "h2 { color: #555; border-bottom: 1px solid #ccc; padding-bottom: 5px; }",
        "h3 { color: #666; }",
        "ul { margin: 10px 0; }",
        "li { margin: 5px 0; }",
        "</style>",
        "</head>",
        "<body>",
    ]

    # Convert markdown to basic HTML
    for line in md_content.split("\n"):
        if line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            html_lines.append(f"<li>{line[2:]}</li>")
        elif line.startswith("**") and line.endswith("**"):
            html_lines.append(f"<strong>{line[2:-2]}</strong>")
        elif line:
            html_lines.append(f"<p>{line}</p>")

    html_lines.extend(["</body>", "</html>"])
    return "\n".join(html_lines)
