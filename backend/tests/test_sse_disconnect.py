import unittest
from pathlib import Path


class SseDisconnectTest(unittest.IsolatedAsyncioTestCase):
    async def test_is_sse_client_disconnected_handles_request_errors(self) -> None:
        from backend.api.sse_utils import is_sse_client_disconnected

        class BrokenRequest:
            async def is_disconnected(self):
                raise RuntimeError("closed")

        self.assertFalse(await is_sse_client_disconnected(BrokenRequest()))

    def test_sse_entrypoints_check_client_disconnect(self) -> None:
        root = Path(__file__).resolve().parents[2]
        targets = [
            root / "backend" / "api" / "study_materials.py",
            root / "backend" / "api" / "tasks.py",
            root / "backend" / "api" / "chat.py",
            root / "backend" / "api" / "question_library.py",
        ]
        for path in targets:
            src = path.read_text(encoding="utf-8")
            self.assertIn("is_sse_client_disconnected", src, str(path.relative_to(root)))


if __name__ == "__main__":
    unittest.main()
