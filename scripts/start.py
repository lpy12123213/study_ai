from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
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

# Dev-stack bookkeeping. The PID file lets `start.py stop` tear down a stack
# started in another window (or orphaned by a crashed launcher); the ports are
# swept as a fallback for leftovers from sessions that predate the PID file.
RUN_DIR = ROOT / ".local" / "run"
DEV_PID_FILE = RUN_DIR / "dev.json"
BACKEND_PORT = 8000
FRONTEND_PORT = 5173

# Graceful shutdown: send the console/signal break to every process group at
# once, wait this long, then force-kill whole trees.
TEARDOWN_GRACE_S = 5.0


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
    except (OSError, UnicodeError):
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


_PLATFORM_LOCK_SUFFIX = {"win32": "win", "linux": "linux", "darwin": "mac"}


def _platform_lock_name(platform: str) -> str | None:
    """Return the lock file name for a platform, or None when unknown.

    Unknown platforms never select a lock and fall back to range resolution.
    """
    suffix = _PLATFORM_LOCK_SUFFIX.get(platform)
    if suffix is None:
        return None
    return f"requirements-lock-{suffix}.txt"


def _selected_requirement_files(root: Path, platform: str) -> list[Path]:
    """Select the requirement files to fingerprint and install for a platform.

    Returns [requirements.txt] plus the platform-specific lock file when that
    exact lock exists (e.g. requirements-lock-win.txt for win32), plus
    requirements-dev.txt when present. A lock generated for another platform is
    never selected: when the matching lock is absent we fall back to range
    resolution from requirements.txt.
    """
    req_files = [root / "requirements.txt"]
    lock_name = _platform_lock_name(platform)
    if lock_name is not None:
        lock_file = root / lock_name
        if lock_file.exists():
            req_files.append(lock_file)
    if (root / "requirements-dev.txt").exists():
        req_files.append(root / "requirements-dev.txt")
    return req_files


def ensure_backend_deps(root: Path, vpy: Path) -> None:
    print("[setup] Checking backend deps...")

    req_files = _selected_requirement_files(root, sys.platform)
    lock_file = next((p for p in req_files if p.name.startswith("requirements-lock-")), None)

    expected = _content_fingerprint(req_files)
    stamp = root / "venv" / ".backend-requirements.sha256"
    installed = _read_text(stamp)

    if expected != installed:
        print("[setup] Installing backend Python packages...")
        _run_checked([str(vpy), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=root)
        if lock_file is not None:
            # 本平台锁定文件存在时按锁定版本安装，保证环境可复现；删除它即回退到区间解析
            _run_checked([str(vpy), "-m", "pip", "install", "-r", str(lock_file)], cwd=root)
        else:
            _run_checked([str(vpy), "-m", "pip", "install", "-r", str(root / "requirements.txt")], cwd=root)
        if (root / "requirements-dev.txt").exists():
            _run_checked([str(vpy), "-m", "pip", "install", "-r", str(root / "requirements-dev.txt")], cwd=root)
        _write_text(stamp, expected)

    # Best-effort Playwright install. If this fails (e.g. offline sandbox), leave a hint.
    try:
        _run_checked([str(vpy), "-m", "playwright", "--version"], cwd=root)
    except RuntimeError:
        _run_checked([str(vpy), "-m", "pip", "install", "playwright"], cwd=root)

    try:
        _run_checked([str(vpy), "-m", "playwright", "install", "chromium"], cwd=root)
    except RuntimeError as exc:
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

    # Benchmark 用例 dry-run：只加载并校验用例 schema，不打后端、不出题。
    # 质量门控（G0-G3 等）是仓库最重要的资产之一，这里保证它们不随 case 文件漂移而坏掉。
    print("[doctor] evals: study_materials --case all --dry-run")
    _run_checked([str(vpy), "-m", "backend.evals.study_materials.runner", "--case", "all", "--dry-run"], cwd=root)
    print("[doctor] evals: question_generation --case all --dry-run")
    _run_checked(
        [str(vpy), "-m", "backend.evals.question_generation.runner", "--case", "all", "--dry-run"], cwd=root
    )

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
        print("[doctor] python -m ruff check backend scripts")
        _run_checked(
            [str(vpy), "-m", "ruff", "check", "backend", "scripts"],
            cwd=root,
        )
    except RuntimeError:
        print("[doctor] ruff not available; skip")

    try:
        npm = _resolve_npm_cmd()
    except RuntimeError:
        print("[doctor] npm not found; skip frontend checks.")
        return

    ensure_frontend_deps(root)
    frontend = root / "frontend"
    print("[doctor] npm run lint")
    _run_checked([npm, "run", "lint"], cwd=frontend)
    print("[doctor] npm run build")
    _run_checked([npm, "run", "build"], cwd=frontend)


# ---------------------------------------------------------------------------
# Process management: spawn / track / teardown
#
# Architectural contract for the dev stack (backend uvicorn + frontend vite):
#
# - Windows: every child is created in its own process group (so we can deliver
#   CTRL_BREAK precisely) and assigned to a Job Object with
#   JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The job guarantees the whole tree
#   (npm.cmd -> node -> vite, uvicorn --reload reloader -> worker) dies even if
#   this launcher itself crashes, because the OS closes the job handle when the
#   process exits.
# - POSIX: children start in their own session; teardown signals and kills the
#   process group, which covers the same descendants.
# - `stop`/`status` work off the PID file first (exact) and port listeners
#   second (sweep for orphans from crashed/older launchers), with a command-line
#   ownership check so unrelated processes sharing the ports are never killed.
# ---------------------------------------------------------------------------


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", ctypes.c_uint),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint),
        ("SchedulingClass", ctypes.c_uint),
    ]


class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE_RIGHT = 0x0001

# Module-level handle: intentionally never closed. It outlives teardown so the
# OS kills any straggler descendants when this process exits.
_job_handle: int | None = None


def _create_kill_on_close_job() -> int | None:
    """Best-effort Windows Job Object with kill-on-close; None if unavailable."""

    if not _is_windows():
        return None
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(handle)
            return None
        return int(handle)
    except Exception:  # noqa: BLE001 - safety net only; taskkill path still works without a job
        return None


def _assign_to_job(job_handle: int | None, pid: int) -> None:
    if not job_handle:
        return
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        rights = _PROCESS_SET_QUOTA | _PROCESS_TERMINATE_RIGHT
        proc_handle = kernel32.OpenProcess(rights, False, pid)
        if not proc_handle:
            return
        try:
            kernel32.AssignProcessToJobObject(ctypes.c_void_p(job_handle), ctypes.c_void_p(proc_handle))
        finally:
            kernel32.CloseHandle(proc_handle)
    except Exception:  # noqa: BLE001 - job membership is best-effort; teardown still force-kills trees
        pass


def _spawn_tracked(cmd: list[str], *, cwd: Path, label: str) -> dict[str, object]:
    """Spawn a dev-stack child in its own process group/session and register it in the job."""

    kwargs: dict[str, object] = {"cwd": str(cwd)}
    if _is_windows():
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kwargs)  # type: ignore[arg-type]
    _assign_to_job(_job_handle, proc.pid)
    return {"label": label, "proc": proc}


def _signal_graceful(proc: subprocess.Popen) -> None:
    """Ask a child process group to shut down (CTRL_BREAK on Windows, SIGINT on POSIX)."""

    try:
        if _is_windows():
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(proc.pid, signal.SIGINT)
    except (OSError, RuntimeError, ValueError):
        pass


def _kill_tree_force(proc: subprocess.Popen | None = None, pid: int | None = None) -> None:
    """Force-kill a child and all of its descendants."""

    target = pid if pid is not None else (proc.pid if proc is not None else None)
    if target is None or target <= 0:
        return
    if _is_windows():
        subprocess.run(
            ["taskkill", "/PID", str(target), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    try:
        os.killpg(target, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(target, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


_teardown_started = False


def _install_stop_handlers() -> None:
    """Turn external stop signals into the same path as Ctrl+C.

    SIGBREAK covers Windows Ctrl+Break; SIGTERM covers `kill <launcher>` on
    POSIX. A second signal during teardown is ignored so it cannot abort the
    cleanup sequence halfway.
    """

    def _raise_interrupt(signum: int, frame: object) -> None:
        del signum, frame
        if _teardown_started:
            return
        raise KeyboardInterrupt

    for sig in (signal.SIGTERM,):
        try:
            signal.signal(sig, _raise_interrupt)
        except (OSError, ValueError):
            pass
    if _is_windows():
        try:
            signal.signal(signal.SIGBREAK, _raise_interrupt)
        except (OSError, ValueError):
            pass


def _teardown(entries: list[dict[str, object]], *, grace_s: float = TEARDOWN_GRACE_S) -> None:
    """Stop all tracked children: graceful signal to every group, then force-kill leftovers."""

    global _teardown_started
    _teardown_started = True

    alive = [e for e in entries if isinstance(e["proc"], subprocess.Popen) and e["proc"].poll() is None]
    if not alive:
        return

    labels = ", ".join(str(e["label"]) for e in alive)
    print(f"[dev] Stopping: {labels}")
    for entry in alive:
        proc = entry["proc"]
        assert isinstance(proc, subprocess.Popen)
        _signal_graceful(proc)

    deadline = time.time() + max(0.0, grace_s)
    while time.time() < deadline:
        alive = [e for e in alive if e["proc"].poll() is None]  # type: ignore[union-attr]
        if not alive:
            return
        time.sleep(0.1)

    for entry in alive:
        proc = entry["proc"]
        assert isinstance(proc, subprocess.Popen)
        print(f"[dev] Force killing {entry['label']} (pid {proc.pid})")
        _kill_tree_force(proc)


# --- PID file --------------------------------------------------------------


def _write_pid_file(entries: list[dict[str, object]], path: Path = DEV_PID_FILE) -> None:
    try:
        procs: list[dict[str, object]] = []
        for entry in entries:
            pid = int(getattr(entry["proc"], "pid", 0) or 0)
            if pid > 0:
                procs.append({"label": str(entry["label"]), "pid": pid})
        payload = {"root": str(ROOT), "started_at": time.time(), "procs": procs}
        _write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
    except (OSError, TypeError, ValueError):
        pass


def _read_pid_file(path: Path = DEV_PID_FILE) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _clear_pid_file(path: Path = DEV_PID_FILE) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _pid_alive_windows(pid: int) -> bool:
    """Canonical Windows liveness probe: SYNCHRONIZE handle + WaitForSingleObject.

    os.kill(pid, 0) is unusable here: on Windows it raises OSError(winerror=87)
    for any process this interpreter does not own, live or dead alike.
    """

    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        synchronize = 0x00100000
        handle = k32.OpenProcess(synchronize, False, pid)
        if not handle:
            # ERROR_ACCESS_DENIED (5) means the process exists but is off-limits;
            # anything else (e.g. ERROR_INVALID_PARAMETER 87) means no such pid.
            return ctypes.get_last_error() == 5
        try:
            wait_timeout = 0x102  # WAIT_TIMEOUT -> still running; WAIT_OBJECT_0 -> terminated
            return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == wait_timeout
        finally:
            k32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:  # noqa: BLE001 - a failed probe is treated as "not alive"
        return False


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _is_windows():
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except PermissionError:
        # Alive but owned by another user; still a live process.
        return True
    except OSError:
        return False
    return True


def _pid_command_line(pid: int) -> str:
    """Best-effort command line for a PID; empty string when unavailable."""

    if pid <= 0:
        return ""
    try:
        if _is_windows():
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            return (out.stdout or "").strip()
        proc_path = Path(f"/proc/{pid}/cmdline")
        if proc_path.exists():
            return proc_path.read_bytes().replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return (out.stdout or "").strip()
    except Exception:  # noqa: BLE001 - ownership check degrades to port/label matching
        return ""


def _cmdline_matches_service(cmdline: str, *, port: int) -> bool:
    """Whether a command line plausibly belongs to this repo's dev services.

    Exact ownership: the repo path appears (venv python, node_modules vite.js).
    Fallback markers (uvicorn backend.app / vite) only apply to the port that
    service would listen on, keeping the blast radius of a false match small.
    """

    text = (cmdline or "").strip()
    if not text:
        return False
    if str(ROOT) in text:
        return True
    if port == BACKEND_PORT and "backend.app" in text:
        return True
    if port == FRONTEND_PORT and "vite" in text.lower():
        return True
    return False


def _parse_windows_netstat_listeners(text: str, *, port: int) -> list[int]:
    """Extract listening PIDs for a port from `netstat -ano -p tcp` output."""

    pids: set[int] = set()
    wanted = f":{port}"
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        if parts[3].upper() != "LISTENING":
            continue
        local = parts[1]
        if not local.endswith(wanted):
            continue
        try:
            pids.add(int(parts[4]))
        except (TypeError, ValueError):
            continue
    return sorted(pids)


def _pids_listening_on_port(port: int) -> list[int]:
    """PIDs currently listening on a TCP port (best-effort, cross-platform)."""

    try:
        if _is_windows():
            # No `-p tcp` filter: vite binds [::1]:5173 (IPv6 loopback) by default,
            # and `-p tcp` can omit the tcpv6 table on some Windows builds.
            out = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            return _parse_windows_netstat_listeners(out.stdout or "", port=port)
        out = subprocess.run(
            ["lsof", "-tnP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if out.returncode == 0 and (out.stdout or "").strip():
            return sorted({int(line) for line in (out.stdout or "").split() if line.isdigit()})
        return []
    except (OSError, subprocess.SubprocessError):
        return []


def _collect_stop_targets() -> dict[int, str]:
    """Map pid -> description for every process `stop` should kill.

    PID-file entries are trusted (we wrote them); port listeners are only
    included when their command line looks like this repo's dev services.
    """

    targets: dict[int, str] = {}

    data = _read_pid_file()
    for entry in data.get("procs") or []:
        if not isinstance(entry, dict):
            continue
        try:
            pid = int(entry.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        label = str(entry.get("label") or f"pid-{pid}")
        if pid and _pid_alive(pid):
            targets[pid] = label

    for port in (BACKEND_PORT, FRONTEND_PORT):
        for pid in _pids_listening_on_port(port):
            if pid in targets:
                continue
            cmdline = _pid_command_line(pid)
            if _cmdline_matches_service(cmdline, port=port):
                targets[pid] = f"port:{port}"
            else:
                print(f"[stop] port {port} is held by unrelated pid {pid}; skipped")
    return targets


def stop_stack() -> int:
    targets = _collect_stop_targets()
    if not targets:
        _clear_pid_file()
        print("[stop] No dev processes found (pid file clean, ports 8000/5173 idle).")
        return 0

    for pid, label in sorted(targets.items()):
        print(f"[stop] Killing {label} (pid {pid})")
        _kill_tree_force(pid=pid)
    _clear_pid_file()
    print("[stop] Done.")
    return 0


def status_stack() -> int:
    data = _read_pid_file()
    entries = [e for e in (data.get("procs") or []) if isinstance(e, dict)]

    print(f"[status] pid file: {DEV_PID_FILE}")
    if not entries:
        print("[status] no recorded dev stack")
    for entry in entries:
        try:
            pid = int(entry.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        label = str(entry.get("label") or f"pid-{pid}")
        state = "running" if _pid_alive(pid) else "dead"
        print(f"[status] {label:<10} pid={pid:<8} {state}")

    for port, name in ((BACKEND_PORT, "backend"), (FRONTEND_PORT, "frontend")):
        pids = _pids_listening_on_port(port)
        if not pids:
            print(f"[status] {name} port {port}: not listening")
        else:
            print(f"[status] {name} port {port}: listening (pid {', '.join(str(p) for p in pids)})")
    return 0


# --- dev stack -------------------------------------------------------------


def _wait_http_ready(url: str, *, timeout_s: float, label: str) -> bool:
    """轮询直到 URL 可访问；用于就绪门控（不判内容，连接成功即认为就绪）。"""

    import urllib.error
    import urllib.request

    deadline = time.time() + max(1.0, timeout_s)
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.5)
    print(f"[dev] WARN: {label} not ready at {url} within {timeout_s:.0f}s; check its output above.")
    return False


def _report_stack_readiness(entries: list[dict[str, object]]) -> None:
    """并行等待 backend/frontend 就绪后再宣告可用（后端冷启动可达数十秒）。"""

    from concurrent.futures import ThreadPoolExecutor

    checks: list[tuple[str, str, float]] = []
    for entry in entries:
        label = str(entry["label"])
        if label == "backend":
            checks.append((label, f"http://127.0.0.1:{BACKEND_PORT}/api/health/live", 90.0))
        elif label == "frontend":
            # vite 默认只绑 IPv6 回环 [::1]:5173；用 localhost 让解析器同时尝试 v4/v6。
            checks.append((label, f"http://localhost:{FRONTEND_PORT}/", 45.0))

    with ThreadPoolExecutor(max_workers=len(checks) or 1) as pool:
        futures = {label: pool.submit(_wait_http_ready, url, timeout_s=timeout_s, label=label) for label, url, timeout_s in checks}
        for label, _, _ in checks:
            if futures[label].result():
                port = BACKEND_PORT if label == "backend" else FRONTEND_PORT
                print(f"[dev] {label} ready at http://127.0.0.1:{port}")


def run_dev(root: Path, *, auto_restart: bool = False) -> None:
    vpy = ensure_venv(root)
    ensure_backend_deps(root, vpy)
    ensure_frontend_deps(root)

    global _job_handle
    _job_handle = _create_kill_on_close_job()

    entries: list[dict[str, object]] = []

    def _track(cmd: list[str], *, cwd: Path, label: str) -> dict[str, object]:
        entry: dict[str, object] = {"label": label, "cmd": list(cmd), "cwd": cwd}
        entry["proc"] = _spawn_tracked(cmd, cwd=cwd, label=label)["proc"]
        return entry

    try:
        npm = _resolve_npm_cmd()

        backend_cmd = [str(vpy), "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
        print("[dev] Starting backend:", " ".join(backend_cmd))
        entries.append(_track(backend_cmd, cwd=root, label="backend"))

        frontend_cmd = [npm, "run", "dev"]
        print("[dev] Starting frontend:", " ".join(frontend_cmd))
        entries.append(_track(frontend_cmd, cwd=root / "frontend", label="frontend"))

        _write_pid_file(entries)
        print(f"[dev] backend  -> http://127.0.0.1:{BACKEND_PORT} (docs at /docs)")
        print(f"[dev] frontend -> http://127.0.0.1:{FRONTEND_PORT} (proxies /api to backend)")
        _report_stack_readiness(entries)
        print("[dev] Press Ctrl+C to stop both.")

        # 每个服务最多重启次数（--auto-restart）：夜间长任务场景下短暂崩溃不应拖垮整栈。
        restart_budget = {"backend": 3, "frontend": 3} if auto_restart else {}

        while True:
            for entry in entries:
                proc = entry["proc"]
                assert isinstance(proc, subprocess.Popen)
                code = proc.poll()
                if code is None:
                    continue
                label = str(entry["label"])
                if auto_restart and restart_budget.get(label, 0) > 0:
                    restart_budget[label] -= 1
                    print(
                        f"[dev] {label} exited with code {code}; "
                        f"restarting ({restart_budget[label]} left) in 2s..."
                    )
                    time.sleep(2.0)
                    entry["proc"] = _spawn_tracked(entry["cmd"], cwd=entry["cwd"], label=label)["proc"]  # type: ignore[index,arg-type]
                    _write_pid_file(entries)
                    continue
                print(f"[dev] {label} exited with code {code}; shutting down the rest.")
                raise SystemExit(code if isinstance(code, int) else 1)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[dev] Ctrl+C received.")
    finally:
        _teardown(entries)
        _clear_pid_file()


def _run_foreground(cmd: list[str], *, cwd: Path) -> int:
    """Run a single service attached to this console; Ctrl+C exits cleanly.

    The child shares the console process group, so a Ctrl+C reaches it
    directly; we only wait for it and sweep the tree if it ignores the signal.
    """

    proc = subprocess.Popen(cmd, cwd=str(cwd))
    try:
        return int(proc.wait())
    except KeyboardInterrupt:
        try:
            return int(proc.wait(timeout=10))
        except subprocess.TimeoutExpired:
            print("[run] process did not exit after Ctrl+C; force killing")
            _kill_tree_force(proc)
            return 130


def main(argv: list[str]) -> int:
    _install_stop_handlers()
    os.chdir(ROOT)
    # 输出重定向到文件时 Python 默认块缓冲，launcher 的进度行会攒在缓冲区里；
    # 统一行缓冲，保证 `start.py dev > log` 也能实时看到 [dev] 行。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)  # type: ignore[union-attr]
        except (AttributeError, OSError, ValueError):
            pass

    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("command", nargs="?", default="dev")
    ap.add_argument("--auto-restart", action="store_true", help="dev: 崩溃后自动重启子进程（每服务最多 3 次）")
    ns, _ = ap.parse_known_args(argv)
    cmd = str(ns.command or "dev").strip().lower()

    if cmd in {"help", "-h", "--help"}:
        print(
            """Usage:
  start.bat                 (dev: backend + frontend)
  start.bat dev             (backend + frontend)
  start.bat dev --auto-restart  (auto-restart crashed children, up to 3x each)
  start.bat all             (alias of dev; MCP stdio server is client-launched)
  start.bat backend         (backend only)
  start.bat frontend        (frontend only)
  start.bat mcp             (MCP stdio server in foreground, for manual wiring)
  start.bat stop            (kill dev stack: pid file + ports 8000/5173 sweep)
  start.bat status          (show dev stack pids and port occupancy)
  start.bat menu            (打开 TUI 启动箱)
  start.bat setup           (install deps only)
  start.bat doctor          (run smoke checks)

Linux/macOS: ./start.sh <command>
"""
        )
        return 0

    if cmd in {"menu", "launch", "tui"}:
        vpy = ensure_venv(ROOT)
        _run_checked([str(vpy), "-m", "backend.cli.launcher"], cwd=ROOT)
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

    if cmd == "stop":
        return stop_stack()

    if cmd == "status":
        return status_stack()

    if cmd == "backend":
        vpy = ensure_venv(ROOT)
        ensure_backend_deps(ROOT, vpy)
        return _run_foreground(
            [str(vpy), "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000", "--reload"],
            cwd=ROOT,
        )

    if cmd == "frontend":
        ensure_frontend_deps(ROOT)
        npm = _resolve_npm_cmd()
        return _run_foreground([npm, "run", "dev"], cwd=ROOT / "frontend")

    if cmd == "mcp":
        # stdio server: meant to be launched by an MCP client (mcp_config.json).
        # Foreground keeps stdin/stdout attached for manual wiring/debugging.
        vpy = ensure_venv(ROOT)
        ensure_backend_deps(ROOT, vpy)
        return _run_foreground([str(vpy), "-m", "backend.mcp.stdio_server"], cwd=ROOT)

    if cmd in {"dev", "all"}:
        # `all` no longer spawns the MCP stdio server in the background: without
        # an MCP client attached to its stdio it just idles. Launch it via
        # `start.bat mcp` or an MCP client config when needed.
        run_dev(ROOT, auto_restart=bool(ns.auto_restart))
        return 0

    print(f"[ERROR] Unknown command: {cmd}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
