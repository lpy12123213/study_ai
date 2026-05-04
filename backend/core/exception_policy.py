from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ExceptionPolicyFinding:
    path: str
    line: int
    kind: str
    message: str


def _is_exception_name(node: ast.AST | None) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Name):
        return node.id in {"Exception", "BaseException"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"Exception", "BaseException"}
    return False


def _is_broad_exception_type(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if _is_exception_name(node):
        return True
    if isinstance(node, ast.Tuple):
        return any(_is_exception_name(item) for item in node.elts)
    return False


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _has_true_exc_info(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg != "exc_info":
            continue
        return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def _handler_log_levels(handler: ast.ExceptHandler) -> set[str]:
    levels: set[str] = set()
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if not name:
            continue
        attr = name.rsplit(".", 1)[-1]
        if attr == "exception":
            levels.add("exception")
        elif attr in {"error", "critical", "warning"} and _has_true_exc_info(node):
            levels.add("exc_info")
        elif attr == "debug":
            levels.add("debug")
    return levels


def _handler_has_raise(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(node, ast.Raise) for node in ast.walk(handler))


def _handler_is_pass_only(handler: ast.ExceptHandler) -> bool:
    meaningful = [node for node in handler.body if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant)]
    return bool(meaningful) and all(isinstance(node, ast.Pass) for node in meaningful)


def scan_source(source: str, *, path: str = "<string>") -> list[ExceptionPolicyFinding]:
    tree = ast.parse(source, filename=path)
    findings: list[ExceptionPolicyFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if not _is_broad_exception_type(node.type):
            continue

        if node.type is None:
            findings.append(
                ExceptionPolicyFinding(
                    path=path,
                    line=node.lineno,
                    kind="bare-except",
                    message="Use a concrete exception type instead of bare except.",
                )
            )

        logs = _handler_log_levels(node)
        if "exception" in logs or "exc_info" in logs or _handler_has_raise(node):
            continue

        kind = "debug-only-broad-except" if "debug" in logs else "silent-broad-except"
        if _handler_is_pass_only(node):
            kind = "pass-only-broad-except"
        findings.append(
            ExceptionPolicyFinding(
                path=path,
                line=node.lineno,
                kind=kind,
                message="Broad exception handlers must re-raise or log with logger.exception/ exc_info=True.",
            )
        )
    return findings


def scan_paths(paths: Iterable[Path]) -> list[ExceptionPolicyFinding]:
    findings: list[ExceptionPolicyFinding] = []
    for path in paths:
        if not path.exists() or not path.is_file() or path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            source = path.read_text(encoding="utf-8", errors="replace")
        findings.extend(scan_source(source, path=path.as_posix()))
    return findings


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if {"__pycache__", ".venv", "venv"} & parts:
            continue
        yield path

