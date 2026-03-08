import os
import tempfile
import unittest
from pathlib import Path

from backend.core.record_replay import RecordReplayStore, fingerprint, record_enabled, replay_enabled


class RecordReplayModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._env_before = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._env_before)

    def test_fingerprint_is_stable_for_dict_key_order(self) -> None:
        fp1 = fingerprint({"a": 1, "b": 2})
        fp2 = fingerprint({"b": 2, "a": 1})
        self.assertEqual(fp1, fp2)
        self.assertEqual(len(fp1), 64)

    def test_replay_enabled_via_mode(self) -> None:
        os.environ.pop("REPLAY", None)
        os.environ["RECORD_REPLAY_MODE"] = "replay"
        self.assertTrue(replay_enabled())
        self.assertFalse(record_enabled())

    def test_record_enabled_via_mode(self) -> None:
        os.environ.pop("RECORD", None)
        os.environ["RECORD_REPLAY_MODE"] = "record"
        self.assertTrue(record_enabled())
        self.assertFalse(replay_enabled())


class RecordReplayStoreTests(unittest.TestCase):
    def test_store_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordReplayStore("unittest", root=Path(tmp))
            request = {"fn": "x", "kwargs": {"a": 1}}
            response = {"success": True, "data": {"ok": 1}}

            key = store.save(request=request, response=response, meta={"note": "test"})
            loaded, loaded_key = store.load(request=request)

            self.assertEqual(key, loaded_key)
            self.assertIsInstance(loaded, dict)
            self.assertEqual(loaded.get("request"), request)
            self.assertEqual(loaded.get("response"), response)

    def test_store_load_missing_fixture_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RecordReplayStore("unittest", root=Path(tmp))
            request = {"fn": "missing", "kwargs": {"a": 1}}
            loaded, key = store.load(request=request)
            self.assertIsNone(loaded)
            self.assertEqual(len(key), 64)


if __name__ == "__main__":
    unittest.main()
