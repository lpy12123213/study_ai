from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware.input_validation import InputValidationMiddleware


class InputValidationNonFiniteNumberTest(unittest.TestCase):
    """Reject non-finite JSON numbers (Infinity/NaN) at the input boundary (F9)."""

    def _client(self) -> TestClient:
        app = FastAPI()

        @app.post("/api/echo")
        async def echo() -> dict:
            return {"ok": True}

        app.add_middleware(InputValidationMiddleware)
        return TestClient(app)

    def _post_raw(self, body: str) -> None:
        # httpx's `json=` serializer refuses non-finite floats, so send the raw
        # literal (which json.loads accepts as Infinity/NaN) with a JSON content-type.
        return self._client().post(
            "/api/echo",
            content=body.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    def test_infinity_literal_rejected_with_400(self) -> None:
        resp = self._post_raw('{"value": Infinity}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error", {}).get("code"), "non_finite_number")

    def test_negative_infinity_literal_rejected_with_400(self) -> None:
        resp = self._post_raw('{"value": -Infinity}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error", {}).get("code"), "non_finite_number")

    def test_nan_literal_rejected_with_400(self) -> None:
        resp = self._post_raw('{"value": NaN}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error", {}).get("code"), "non_finite_number")

    def test_huge_exponent_overflows_to_infinity_and_is_rejected(self) -> None:
        resp = self._post_raw('{"value": 1e999}')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error", {}).get("code"), "non_finite_number")

    def test_finite_numbers_pass_through(self) -> None:
        resp = self._post_raw('{"value": 42.5}')
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
