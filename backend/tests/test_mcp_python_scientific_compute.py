import unittest

from backend.mcp.tools.python_scientific_compute import python_scientific_compute


class PythonScientificComputeTests(unittest.IsolatedAsyncioTestCase):
    async def test_executes_basic_math_and_returns_result(self) -> None:
        result = await python_scientific_compute(
            code="""
x = 3
y = 4
result = (x ** 2 + y ** 2) ** 0.5
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("result_repr"), "5.0")
        self.assertEqual(result.get("result_type"), "float")

    async def test_uses_last_expression_when_result_not_assigned(self) -> None:
        result = await python_scientific_compute(
            code="""
import math
math.factorial(6)
""".strip()
        )

        self.assertFalse(result.get("success"))
        self.assertIn("不允许", str(result.get("error") or ""))

        result = await python_scientific_compute(
            code="""
math.factorial(6)
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("result_repr"), "720")
        self.assertEqual(result.get("result_type"), "int")

    async def test_captures_stdout(self) -> None:
        result = await python_scientific_compute(
            code="""
print('intermediate=', 42)
result = 7 * 8
""".strip()
        )

        self.assertTrue(result.get("success"))
        self.assertIn("intermediate= 42", str(result.get("stdout") or ""))
        self.assertEqual(result.get("result_repr"), "56")


if __name__ == "__main__":
    unittest.main()
