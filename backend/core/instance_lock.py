"""后端单实例标记（用于任务恢复的误杀保护）。

`task_runtime.restart_recovery` 在启动时会把数据库里遗留的 running 任务标记
失败。当两个后端实例共享同一个 SQLite 文件时（benchmark / 测试套件与服务并行），
后启动的实例会把先启动实例的**活任务**误杀。这里用一个轻量的 PID 锁文件
（`.local/run/backend-instance.json`）判断"是否仍有另一个实例存活"：
存活则跳过恢复；锁不存在或持有者已死则正常恢复并接管锁。

已知边界（接受）：PID 复用可能让死锁看起来存活——此时最多是跳过了一次恢复，
不会误杀；锁粒度是仓库目录而非数据库文件，同仓库多库场景会保守跳过。
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import time
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _default_lock_path() -> Path:
    return _REPO_ROOT / ".local" / "run" / "backend-instance.json"


def _pid_alive(pid: int) -> bool:
    """跨平台进程存活探测。

    Windows 上 os.kill(pid, 0) 对非本进程子进程一律抛 winerror=87（活死不分），
    必须用 OpenProcess(SYNCHRONIZE) + WaitForSingleObject 的规范做法。
    """

    if pid <= 0:
        return False
    if platform.system().lower().startswith("win"):
        try:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            k32.OpenProcess.restype = ctypes.c_void_p
            handle = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not handle:
                return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED -> 存在但无权限
            try:
                return k32.WaitForSingleObject(ctypes.c_void_p(handle), 0) == 0x102  # WAIT_TIMEOUT
            finally:
                k32.CloseHandle(ctypes.c_void_p(handle))
        except Exception:  # noqa: BLE001 - 探测失败按"不存活"处理，恢复流程照常进行
            return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _read_lock(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def other_live_backend_instance(path: Optional[Path] = None) -> Optional[dict]:
    """返回存活的其他后端实例信息；无锁/持有者已死/数据损坏返回 None。"""

    data = _read_lock(path or _default_lock_path())
    try:
        pid = int(data.get("pid") or 0)
    except (TypeError, ValueError):
        return None
    if pid <= 0 or pid == os.getpid() or not _pid_alive(pid):
        return None
    return {"pid": pid, "started_at": data.get("started_at")}


def mark_backend_instance_started(path: Optional[Path] = None) -> None:
    """把当前进程登记为活跃后端实例（仅在无其他存活持有时写入）。"""

    target = path or _default_lock_path()
    if other_live_backend_instance(target) is not None:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"pid": os.getpid(), "started_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def clear_backend_instance_lock(path: Optional[Path] = None) -> None:
    """清锁（测试与显式下线用）；不存在时静默。"""

    try:
        (path or _default_lock_path()).unlink(missing_ok=True)
    except OSError:
        pass
