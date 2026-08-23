from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


def load_start_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "start.py"
    spec = importlib.util.spec_from_file_location("study_ai_start_script", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load scripts/start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FrontendDistStalenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "frontend" / "src").mkdir(parents=True)
        (self.root / "frontend" / "dist").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_with_mtime(self, rel: str, content: str, mtime: float) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        os.utime(path, (mtime, mtime))

    def test_reports_stale_dist_when_source_is_newer(self) -> None:
        self.write_with_mtime("frontend/dist/assets/app.js", "old build", 1000)
        self.write_with_mtime("frontend/src/App.tsx", "new source", 2000)

        stale, message = self.start.frontend_dist_staleness(self.root)

        self.assertTrue(stale)
        self.assertIn("frontend/dist is stale", message)
        self.assertIn("npm run build", message)

    def test_accepts_dist_newer_than_source(self) -> None:
        self.write_with_mtime("frontend/src/App.tsx", "source", 1000)
        self.write_with_mtime("frontend/dist/assets/app.js", "new build", 2000)

        stale, message = self.start.frontend_dist_staleness(self.root)

        self.assertFalse(stale)
        self.assertEqual("", message)

    def test_missing_dist_does_not_warn_for_dev_mode(self) -> None:
        self.write_with_mtime("frontend/src/App.tsx", "source", 1000)
        for item in (self.root / "frontend" / "dist").glob("*"):
            if item.is_file():
                item.unlink()
        (self.root / "frontend" / "dist").rmdir()

        stale, message = self.start.frontend_dist_staleness(self.root)

        self.assertFalse(stale)
        self.assertEqual("", message)


class SelectedRequirementFilesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write(self, name: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content\n", encoding="utf-8")

    def names(self, files: list[Path]) -> list[str]:
        return [p.name for p in files]

    def test_win32_selects_win_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-win.txt")
        self.write("requirements-dev.txt")

        files = self.start._selected_requirement_files(self.root, "win32")

        self.assertEqual(
            ["requirements.txt", "requirements-lock-win.txt", "requirements-dev.txt"],
            self.names(files),
        )

    def test_win32_falls_back_when_only_linux_lock_present(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-linux.txt")
        self.write("requirements-dev.txt")

        files = self.start._selected_requirement_files(self.root, "win32")

        self.assertEqual(["requirements.txt", "requirements-dev.txt"], self.names(files))

    def test_linux_selects_linux_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-win.txt")
        self.write("requirements-lock-linux.txt")

        files = self.start._selected_requirement_files(self.root, "linux")

        self.assertEqual(["requirements.txt", "requirements-lock-linux.txt"], self.names(files))

    def test_darwin_selects_mac_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-mac.txt")

        files = self.start._selected_requirement_files(self.root, "darwin")

        self.assertEqual(["requirements.txt", "requirements-lock-mac.txt"], self.names(files))

    def test_no_lock_falls_back_to_ranges(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-dev.txt")

        files = self.start._selected_requirement_files(self.root, "win32")

        self.assertEqual(["requirements.txt", "requirements-dev.txt"], self.names(files))

    def test_unknown_platform_never_selects_a_lock(self) -> None:
        self.write("requirements.txt")
        self.write("requirements-lock-win.txt")

        files = self.start._selected_requirement_files(self.root, "freebsd")

        self.assertEqual(["requirements.txt"], self.names(files))

    def test_platform_lock_name_mapping(self) -> None:
        self.assertEqual("requirements-lock-win.txt", self.start._platform_lock_name("win32"))
        self.assertEqual("requirements-lock-linux.txt", self.start._platform_lock_name("linux"))
        self.assertEqual("requirements-lock-mac.txt", self.start._platform_lock_name("darwin"))
        self.assertIsNone(self.start._platform_lock_name("freebsd"))


class WindowsNetstatParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()

    def test_extracts_listening_pids_for_port_across_v4_and_v6(self) -> None:
        text = "\n".join(
            [
                "  Proto  Local Address          Foreign Address        State           PID",
                "  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       1111",
                "  TCP    [::]:8000              [::]:0                 LISTENING       2222",
                "  TCP    127.0.0.1:8000         127.0.0.1:5000         ESTABLISHED     3333",
                "  TCP    0.0.0.0:5173           0.0.0.0:0              LISTENING       4444",
                "  TCP    0.0.0.0:18000          0.0.0.0:0              LISTENING       5555",
            ]
        )
        self.assertEqual(self.start._parse_windows_netstat_listeners(text, port=8000), [1111, 2222])
        self.assertEqual(self.start._parse_windows_netstat_listeners(text, port=5173), [4444])
        self.assertEqual(self.start._parse_windows_netstat_listeners(text, port=9999), [])

    def test_ignores_malformed_lines(self) -> None:
        text = "garbage line\nTCP 0.0.0.0:8000 0.0.0.0:0 LISTENING not-a-pid\nUDP 0.0.0.0:8000 *:* 1234\n"
        self.assertEqual(self.start._parse_windows_netstat_listeners(text, port=8000), [])


class PidFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_roundtrip_and_clear(self) -> None:
        path = Path(self.tmp.name) / "nested" / "dev.json"

        class _FakeProc:
            pid = 4242

        entries = [
            {"label": "backend", "proc": _FakeProc()},
            {"label": "frontend", "proc": _FakeProc()},
        ]
        self.start._write_pid_file(entries, path=path)
        data = self.start._read_pid_file(path=path)
        self.assertEqual([p["pid"] for p in data["procs"]], [4242, 4242])
        self.assertEqual([p["label"] for p in data["procs"]], ["backend", "frontend"])
        self.assertEqual(data["root"], str(self.start.ROOT))

        self.start._clear_pid_file(path=path)
        self.assertEqual(self.start._read_pid_file(path=path), {})

    def test_read_missing_or_corrupt_file_returns_empty_dict(self) -> None:
        with self.subTest(case="missing"):
            self.assertEqual(self.start._read_pid_file(path=Path("Z:/no/such/file.json")), {})
        with self.subTest(case="corrupt"):
            path = Path(self.tmp.name) / "dev.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(self.start._read_pid_file(path=path), {})


class PidHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = load_start_module()

    def test_pid_alive_rejects_non_positive_and_accepts_self(self) -> None:
        self.assertFalse(self.start._pid_alive(0))
        self.assertFalse(self.start._pid_alive(-1))
        self.assertTrue(self.start._pid_alive(os.getpid()))

    def test_cmdline_matches_service(self) -> None:
        root = str(self.start.ROOT)
        cases = [
            (f"{root}\\venv\\Scripts\\python.exe -m uvicorn backend.app:app", self.start.BACKEND_PORT, True),
            (f"{root}\\frontend\\node_modules\\vite\\bin\\vite.js", self.start.FRONTEND_PORT, True),
            ("python -m uvicorn backend.app:app --port 8000", self.start.BACKEND_PORT, True),
            ("node C:/tools/vite.js", self.start.FRONTEND_PORT, True),
            # 标记只对匹配的端口生效：vite 标记不认领 8000，backend.app 标记不认领 5173。
            ("node C:/tools/vite.js", self.start.BACKEND_PORT, False),
            ("python -m uvicorn backend.app:app", self.start.FRONTEND_PORT, False),
            ("python -m http.server 8000", self.start.BACKEND_PORT, False),
            ("", self.start.BACKEND_PORT, False),
        ]
        for cmdline, port, expected in cases:
            with self.subTest(cmdline=cmdline, port=port):
                self.assertEqual(self.start._cmdline_matches_service(cmdline, port=port), expected)


if __name__ == "__main__":
    unittest.main()
