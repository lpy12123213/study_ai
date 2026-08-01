import unittest

from backend.generation.study_materials.author.blueprint import Blueprint
from backend.generation.study_materials.author.todos import TodoItem, TodoList
from backend.generation.study_materials.quality_gate import evaluate_author_acceptance

BP = Blueprint.from_dict({
    "narrative": "n", "terminology": [{"symbol": "$\\epsilon$", "meaning": "任意小的正数"}],
    "sections": [{"id": "sec-1", "title": "t", "purpose": "p", "key_points": ["k"],
                  "target_chars": 800, "difficulty": "基础", "misconceptions": [],
                  "frontier": False}],
    "figures": [],
})

CLEAN_MARKDOWN = "# 极限\n\n$\\epsilon$ 表示任意小的正数，用于刻画极限。"


def _cleared_todos() -> TodoList:
    return TodoList(items=[
        TodoItem(id="t1", type="backbone", status="done"),
        TodoItem(id="t2", type="fill", ref="sec-1", status="waived"),
    ])


def _issue_codes(report: dict, *, severity: str | None = None) -> list[str]:
    issues = report["issues"]
    if severity is None:
        return [issue["code"] for issue in issues]
    return [issue["code"] for issue in issues if issue["severity"] == severity]


class AuthorAcceptanceGateTests(unittest.TestCase):
    def test_pending_todos_rejected(self):
        todos = TodoList(items=[
            TodoItem(id="t1", type="fill", ref="sec-1", status="done"),
            TodoItem(id="t2", type="fig", ref="1", status="pending"),
        ])

        report = evaluate_author_acceptance(todos=todos, markdown=CLEAN_MARKDOWN, blueprint=BP)

        self.assertFalse(report["passed"])
        self.assertIn("todos_not_cleared", _issue_codes(report))
        self.assertIn("todos_not_cleared", report["failed_checks"])

    def test_placeholder_residual_rejected(self):
        for markdown in ("# 极限\n\n正文 [[FILL:sec-1]] 待补。", "# 极限\n\n见图 [[FIG:1]]。"):
            with self.subTest(markdown=markdown):
                report = evaluate_author_acceptance(todos=_cleared_todos(), markdown=markdown, blueprint=BP)

                self.assertFalse(report["passed"])
                self.assertIn("placeholder_residual", _issue_codes(report))
                self.assertIn("placeholder_residual", report["failed_checks"])

    def test_terminology_conflict_is_warning_and_does_not_block(self):
        # 表内 $\\epsilon$ = 任意小的正数，正文另定义为“误差上界”，含义冲突。
        markdown = "# 极限\n\n$\\epsilon$ 表示误差上界，随迭代递减。"

        report = evaluate_author_acceptance(todos=_cleared_todos(), markdown=markdown, blueprint=BP)

        self.assertTrue(report["passed"])
        self.assertIn("terminology_conflict", _issue_codes(report, severity="warning"))
        self.assertNotIn("terminology_conflict", report["failed_checks"])

    def test_all_cleared_passes(self):
        report = evaluate_author_acceptance(todos=_cleared_todos(), markdown=CLEAN_MARKDOWN, blueprint=BP)

        self.assertTrue(report["passed"])
        self.assertEqual(report["issues"], [])
        self.assertEqual(report["failed_checks"], [])

    def test_report_shape_matches_gate_convention(self):
        report = evaluate_author_acceptance(todos=_cleared_todos(), markdown=CLEAN_MARKDOWN, blueprint=BP)

        self.assertIn("passed", report)
        self.assertIn("failed_checks", report)
        self.assertIn("issues", report)
        self.assertIn("quality_policy_version", report)
        self.assertIsInstance(report["issues"], list)
        for issue in report["issues"]:
            self.assertIn("code", issue)
            self.assertIn("severity", issue)

    def test_empty_todo_list_counts_as_cleared(self):
        report = evaluate_author_acceptance(todos=TodoList(), markdown=CLEAN_MARKDOWN, blueprint=BP)

        self.assertTrue(report["passed"])


if __name__ == "__main__":
    unittest.main()
