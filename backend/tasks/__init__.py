"""Long-running task entrypoints (submit + runners)."""
from backend.tasks.submit import (
    submit_deepthink_task,
    submit_essay_evaluation_task,
    submit_export_paper_task,
    submit_export_study_archive_task,
    submit_generate_full_paper_task,
    submit_knowledge_video_task,
    submit_lesson_plan_task,
    submit_paper_compose_task,
    submit_question_evaluate_task,
)

__all__ = [
    "submit_deepthink_task",
    "submit_essay_evaluation_task",
    "submit_export_paper_task",
    "submit_export_study_archive_task",
    "submit_generate_full_paper_task",
    "submit_knowledge_video_task",
    "submit_lesson_plan_task",
    "submit_paper_compose_task",
    "submit_question_evaluate_task",
]
