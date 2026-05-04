from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from backend.core.exception_policy import scan_source
from scripts.audit.exception_policy import main as exception_policy_main


class ExceptionPolicyTests(unittest.TestCase):
    def test_flags_bare_and_silent_broad_handlers(self) -> None:
        findings = scan_source(
            """
def a():
    try:
        work()
    except:
        pass

def b(logger):
    try:
        work()
    except Exception:
        logger.debug("ignored")
""",
            path="sample.py",
        )

        self.assertEqual([f.kind for f in findings], ["bare-except", "pass-only-broad-except", "debug-only-broad-except"])

    def test_allows_reraise_and_exception_logging(self) -> None:
        findings = scan_source(
            """
def a(logger):
    try:
        work()
    except Exception:
        logger.exception("failed")

def b():
    try:
        work()
    except Exception:
        raise
""",
            path="sample.py",
        )

        self.assertEqual(findings, [])

    def test_allows_concrete_exception_without_policy_warning(self) -> None:
        findings = scan_source(
            """
def a(logger):
    try:
        work()
    except ValueError:
        logger.debug("invalid user input")
""",
            path="sample.py",
        )

        self.assertEqual(findings, [])

    def test_cli_strict_supports_finding_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.py"
            path.write_text(
                """
def a():
    try:
        work()
    except Exception:
        pass
""",
                encoding="utf-8",
            )

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = exception_policy_main(
                    [str(path), "--strict", "--max-total", "1", "--max-kind", "pass-only-broad-except=1"]
                )
            self.assertEqual(code, 0)
            self.assertIn("strict budget ok", out.getvalue())

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = exception_policy_main(
                    [str(path), "--strict", "--max-total", "0", "--max-kind", "pass-only-broad-except=0"]
                )
            self.assertEqual(code, 1)
            self.assertIn("strict budget exceeded", out.getvalue())


if __name__ == "__main__":
    unittest.main()
