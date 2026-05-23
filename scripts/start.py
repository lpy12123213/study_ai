from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# Keep Playwright browser caches inside the repo so dev/doctor runs don't need to
# write to the user's profile (and so the cache is easy to clean up).
#
# If users prefer the global default cache location, they can override via env.
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".local" / "ms-playwright"))


def _is_windows() -> bool:
    return platform.system().lower().startswith("win")


def _venv_python(root: Path) -> Path:
    if _is_windows():
        return root / "venv" / "Scripts" / "python.exe"
    return root / "venv" / "bin" / "python"


def _content_fingerprint(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for path in paths:
        if not path.exists():
            continue
        h.update(f"## {path.as_posix()}\n".encode("utf-8"))
        h.update(path.read_bytes())
        h.update(b"\n")
    return h.hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _run_checked(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"command_failed code={proc.returncode} cmd={' '.join(cmd)}")


def _resolve_npm_cmd() -> str:
    # On Windows, `npm` is typically `npm.cmd`. Python's subprocess does not
    # reliably resolve PATHEXT the same way shells do, so prefer the .cmd path.
    npm = shutil.which("npm.cmd") or shutil.which("npm.exe")
    if npm:
        return npm
    npm = shutil.which("npm")
    if npm:
        return npm
    raise RuntimeError("npm_not_found")


def ensure_venv(root: Path) -> Path:
    """Ensure repo-local venv exists; return the venv python path."""

    vpy = _venv_python(root)
    if vpy.exists():
        return vpy

    print("[setup] Creating virtual environment...")
    _run_checked([sys.executable, "-m", "venv", str(root / "venv")], cwd=root)
    if not vpy.exists():
        raise RuntimeError(f"venv_create_failed python_not_found={vpy}")
    return vpy


def ensure_backend_deps(root: Path, vpy: Path) -> None:
    print("[setup] Checking backend deps...")

    req_files = [root / "requirements.txt"]
    if (root / "requirements-dev.txt").exists():
        req_files.append(root / "requirements-dev.txt")

    expected = _content_fingerprint(req_files)
    stamp = root / "venv" / ".backend-requirements.sha256"
    installed = _read_text(stamp)

    if expected != installed:
        print("[setup] Installing backend Python packages...")
        _run_checked([str(vpy), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=root)
        _run_checked([str(vpy), "-m", "pip", "install", "-r", str(root / "requirements.txt")], cwd=root)
        if (root / "requirements-dev.txt").exists():
            _run_checked([str(vpy), "-m", "pip", "install", "-r", str(root / "requirements-dev.txt")], cwd=root)
        _write_text(stamp, expected)

    # Best-effort Playwright install. If this fails (e.g. offline sandbox), leave a hint.
    try:
        _run_checked([str(vpy), "-m", "playwright", "--version"], cwd=root)
    except Exception:
        _run_checked([str(vpy), "-m", "pip", "install", "playwright"], cwd=root)

    try:
        _run_checked([str(vpy), "-m", "playwright", "install", "chromium"], cwd=root)
    except Exception as exc:
        # Playwright browser download can fail in restricted/offline environments.
        # The core app and unit tests do not require browsers, so treat as best-effort.
        print(f"[setup] WARN: Playwright browser install failed: {exc}")
        print("[setup] WARN: You can retry later with: python -m playwright install chromium")


def ensure_frontend_deps(root: Path) -> None:
    npm = _resolve_npm_cmd()

    print("[setup] Checking frontend deps...")
    frontend = root / "frontend"
    node_modules = frontend / "node_modules"
    stamp = node_modules / ".deps.sha256"

    pkg_files = [frontend / "package.json"]
    if (frontend / "package-lock.json").exists():
        pkg_files.append(frontend / "package-lock.json")

    expected = _content_fingerprint(pkg_files)
    installed = _read_text(stamp)

    if (not node_modules.exists()) or expected != installed:
        print("[setup] Installing frontend deps...")
        try:
            _run_checked([npm, "install"], cwd=frontend)
            _write_text(stamp, expected)
        except Exception as exc:
            # If deps cannot be installed (offline / sandbox), but node_modules exists,
            # let downstream checks decide whether the current deps are usable.
            if node_modules.exists():
                print(f"[setup] WARN: npm install failed: {exc}")
            else:
                raise


def _newest_file_mtime(root: Path) -> float:
    if not root.exists():
        return 0.0
    newest = 0.0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def frontend_dist_staleness(root: Path) -> tuple[bool, str]:
    """Return whether the checked-in frontend build is older than source."""

    frontend = root / "frontend"
    src = frontend / "src"
    dist = frontend / "dist"
    if not dist.exists():
        return False, ""

    newest_src = _newest_file_mtime(src)
    newest_dist = _newest_file_mtime(dist)
    if newest_src <= 0.0 or newest_dist <= 0.0:
        return False, ""
    if newest_src <= newest_dist:
        return False, ""
    return True, "frontend/dist is stale; run `cd frontend && npm run build` before packaging or serving static assets."


def doctor(root: Path) -> None:
    vpy = ensure_venv(root)
    ensure_backend_deps(root, vpy)

    print("[doctor] python -m compileall . -q")
    _run_checked([str(vpy), "-m", "compileall", ".", "-q"], cwd=root)

    print("[doctor] import backend.app, backend.mcp.stdio_server")
    _run_checked([str(vpy), "-c", "import backend.app, backend.mcp.stdio_server"], cwd=root)

    print("[doctor] python -m pip check")
    _run_checked([str(vpy), "-m", "pip", "check"], cwd=root)

    print("[doctor] python -m unittest discover -s backend/tests -p test_*.py")
    _run_checked([str(vpy), "-m", "unittest", "discover", "-s", "backend/tests", "-p", "test_*.py"], cwd=root)

    print("[doctor] python scripts/audit/structure_lint.py --strict")
    _run_checked([str(vpy), str(root / "scripts" / "audit" / "structure_lint.py"), "--strict"], cwd=root)

    print("[doctor] python scripts/audit/exception_policy.py backend --strict --max-total 0")
    _run_checked(
        [
            str(vpy),
            str(root / "scripts" / "audit" / "exception_policy.py"),
            "backend",
            "--strict",
            "--max-total",
            "0",
            "--max-kind",
            "pass-only-broad-except=0",
            "--limit",
            "0",
        ],
        cwd=root,
    )

    # Best-effort Ruff; if not installed, skip without failing.
    try:
        print("[doctor] python -m ruff check backend (maintained paths)")
        _run_checked([str(vpy), "-m", "ruff", "check", "backend/api", "backend/chat", "backend/core", "backend/tests"], cwd=root)
    except Exception:
        print("[doctor] ruff not available; skip")

    try:
        npm = _resolve_npm_cmd()
    except Exception:
        print("[doctor] npm not found; skip frontend checks.")
        return

    ensure_frontend_deps(root)
    frontend = root / "frontend"
    print("[doctor] npm run lint")
    _run_checked([npm, "run", "lint"], cwd=frontend)
    print("[doctor] npm run build")
    _run_checked([npm, "run", "build"], cwd=frontend)


def _terminate_process(proc: subprocess.Popen, *, grace_s: float = 4.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if _is_windows():
            proc.terminate()
        else:
            proc.send_signal(signal.SIGINT)
    except Exception:
        pass
    deadline = time.time() + max(0.0, grace_s)
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)
    try:
        proc.kill()
    except Exception:
        pass


def _spawn(cmd: list[str], *, cwd: Path) -> subprocess.Popen:
    return subprocess.Popen(cmd, cwd=str(cwd))


def run_dev(root: Path, *, include_mcp: bool) -> None:
    vpy = ensure_venv(root)
    ensure_backend_deps(root, vpy)
    ensure_frontend_deps(root)

    procs: list[subprocess.Popen] = []

    try:
        npm = _resolve_npm_cmd()

        backend_cmd = [str(vpy), "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
        print("[dev] Starting backend:", " ".join(backend_cmd))
        procs.append(_spawn(backend_cmd, cwd=root))

        if include_mcp:
            mcp_cmd = [str(vpy), "-m", "backend.mcp.stdio_server"]
            print("[dev] Starting mcp:", " ".join(mcp_cmd))
            procs.append(_spawn(mcp_cmd, cwd=root))

        frontend_cmd = [npm, "run", "dev"]
        print("[dev] Starting frontend:", " ".join(frontend_cmd))
        procs.append(_spawn(frontend_cmd, cwd=root / "frontend"))

        # Wait until one exits; then tear down the rest.
        while True:
            for p in procs:
                code = p.poll()
                if code is not None:
                    raise SystemExit(code)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[dev] Stopping...")
    finally:
        for p in reversed(procs):
            _terminate_process(p)


def main(argv: list[str]) -> int:
    os.chdir(ROOT)

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("command", nargs="?", default="dev")
    ns, _ = ap.parse_known_args(argv)
    cmd = str(ns.command or "dev").strip().lower()

    if cmd in {"help", "-h", "--help"}:
        print(
            """Usage:
  start.bat                 (dev: backend + frontend)
  start.bat dev             (backend + frontend)
  start.bat all             (backend + frontend + mcp)
  start.bat backend         (backend only)
  start.bat frontend        (frontend only)
  start.bat mcp             (mcp only)
  start.bat setup           (install deps only)
  start.bat doctor          (run smoke checks)

Linux/macOS: ./start.sh <command>
"""
        )
        return 0

    if cmd == "setup":
        vpy = ensure_venv(ROOT)
        ensure_backend_deps(ROOT, vpy)
        ensure_frontend_deps(ROOT)
        print("Setup complete.")
        return 0

    if cmd == "doctor":
        doctor(ROOT)
        print("Doctor checks passed.")
        return 0

    if cmd == "backend":
        vpy = ensure_venv(ROOT)
        ensure_backend_deps(ROOT, vpy)
        _run_checked([str(vpy), "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"], cwd=ROOT)
        return 0

    if cmd == "frontend":
        ensure_frontend_deps(ROOT)
        npm = _resolve_npm_cmd()
        _run_checked([npm, "run", "dev"], cwd=ROOT / "frontend")
        return 0

    if cmd == "mcp":
        vpy = ensure_venv(ROOT)
        ensure_backend_deps(ROOT, vpy)
        _run_checked([str(vpy), "-m", "backend.mcp.stdio_server"], cwd=ROOT)
        return 0

    if cmd in {"dev", "all"}:
        run_dev(ROOT, include_mcp=(cmd == "all"))
        return 0

    print(f"[ERROR] Unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
