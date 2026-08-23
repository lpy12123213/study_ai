"""共享的模型可用性自检状态。

`backend.app` 的启动自检把逐 role 结果写入这里，`/api/system/model-status`
读取（或触发重跑），前端顶栏据此把"余额不足/模型 id 写错"这类永久性故障
从"生成失败后排障"提前为"常驻可见"。
"""

from __future__ import annotations

import time
from typing import Any, Optional

# 单例状态：进程内只有一份自检结果；读写都发生在事件循环线程，无锁。
_state: dict[str, Any] = {"status": "unknown", "checked_at": None, "roles": []}


def record_model_health(roles: list[dict[str, Any]]) -> dict[str, Any]:
    """写入一轮自检结果并返回汇总。roles 为空表示无可检模型（skipped）。"""

    if not roles:
        overall = "skipped"
    elif any(str(r.get("status")) == "failed" for r in roles):
        overall = "failed"
    elif any(str(r.get("status")) in {"degraded", "error"} for r in roles):
        overall = "degraded"
    else:
        overall = "ok"

    _state["status"] = overall
    _state["checked_at"] = time.time()
    _state["roles"] = [dict(r) for r in roles]
    return get_model_health()


def get_model_health() -> dict[str, Any]:
    return {
        "status": str(_state.get("status") or "unknown"),
        "checked_at": _state.get("checked_at"),
        "roles": [dict(r) for r in (_state.get("roles") or [])],
    }


def reset_model_health_for_tests(status: str = "unknown", checked_at: Optional[float] = None) -> None:
    _state["status"] = status
    _state["checked_at"] = checked_at
    _state["roles"] = []
