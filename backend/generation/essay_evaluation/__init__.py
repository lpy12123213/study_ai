"""Essay evaluation domain.

Multi-dimensional AI scoring for Chinese / English compositions.

Public surface:

- :func:`backend.generation.essay_evaluation.service.evaluate_essay` – one-shot
  evaluator that returns the scoring envelope used by the API + history table.
- :func:`backend.generation.essay_evaluation.runner.run_essay_evaluation_task` –
  ``TaskRuntime`` runner that emits SSE progress events while the LLM scores
  each rubric dimension.

Persistence lives in
:mod:`backend.database.repositories.generation.essay_evaluations`. The
generation/runner code never touches the DB directly so the same scoring
service can be reused from the CLI or future batch tooling.
"""

from backend.generation.essay_evaluation.essay_schemas import (
    EssayEvaluationRequest,
    EssayEvaluationResult,
    EssayParagraphFeedback,
    EssayScore,
)
from backend.generation.essay_evaluation.service import evaluate_essay

__all__ = [
    "EssayEvaluationRequest",
    "EssayEvaluationResult",
    "EssayParagraphFeedback",
    "EssayScore",
    "evaluate_essay",
]
