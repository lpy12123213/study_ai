from __future__ import annotations

import ast
import asyncio
import builtins
import cmath
import decimal
import fractions
import io
import json
import math
import statistics
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Tuple

from backend.core.logging_utils import get_logger

logger = get_logger(__name__)


SCIENTIFIC_COMPUTE_INPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": (
                "要执行的 Python 科学计算代码。\n"
                "【重要约束】\n"
                "1. 禁止使用 import 语句，所有模块已预加载；\n"
                "2. 可直接使用的模块：math、cmath、statistics、fractions、decimal；\n"
                "3. 可选模块（视环境而定）：np（NumPy）、sp（SymPy）；\n"
                "4. 可使用的内置函数：abs、min、max、sum、sorted、round、len、range、enumerate、zip、all、any、list、tuple、set、dict、float、int、complex、bool、str、print；\n"
                "5. 禁止使用双下划线开头的标识符或属性；\n"
                "6. 禁止调用 eval、exec、compile、open、input、__import__ 等危险函数；\n"
                "7. 代码长度不超过 6000 字符，AST 节点不超过 800 个；\n"
                "8. 若需返回结果，请将最终值赋给变量 `result`，或将其作为代码最后一行的表达式。"
            ),
        },
        "purpose": {
            "type": "string",
            "description": "本次计算的目的（可选，用于日志与追踪）",
            "default": "",
        },
        "timeout_seconds": {
            "type": "integer",
            "description": "超时秒数（1-15）",
            "default": 5,
        },
    },
    "required": ["code"],
}


def openai_tool_spec() -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "python_scientific_compute",
            "description": (
                "【Python 科学计算沙盒】在受限环境中执行 Python 科学计算代码。\n"
                "【适用场景】公式验证、方程求解、数值计算、矩阵运算、符号推导、样例枚举等。\n"
                "【预加载模块】math、cmath、statistics、fractions、decimal（始终可用）；np（NumPy）、sp（SymPy）视环境而定。\n"
                "【安全限制】\n"
                "  - 禁止 import 语句（所有可用模块已预加载）；\n"
                "  - 禁止危险函数：eval、exec、compile、open、input、__import__、getattr、setattr 等；\n"
                "  - 禁止双下划线开头的标识符或属性访问；\n"
                "  - 代码长度 ≤ 6000 字符，AST 节点 ≤ 800 个。\n"
                "【返回结果】将最终计算值赋给变量 `result`，或将其作为代码最后一行的表达式。\n"
                "【超时设置】默认 5 秒，范围 1-15 秒。超时将终止进程并返回错误。"
            ),
            "parameters": SCIENTIFIC_COMPUTE_INPUT_SCHEMA,
        },
    }


_ALLOWED_ROOT_NAMES = {
    "math", "cmath", "statistics", "fractions", "decimal", "np", "sp",
    "Fraction", "Decimal", "abs", "min", "max", "sum", "sorted", "round",
    "len", "range", "enumerate", "zip", "all", "any", "list", "tuple",
    "set", "dict", "float", "int", "complex", "bool", "str", "print", "result",
}

_BANNED_CALL_NAMES = {
    "eval",
    "exec",
    "compile",
    "open",
    "__import__",
    "input",
    "help",
    "globals",
    "locals",
    "vars",
    "dir",
    "getattr",
    "setattr",
    "delattr",
    "type",
    "memoryview",
    "bytearray",
}

_ALLOWED_NODE_TYPES: Tuple[type, ...] = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.Call, ast.Attribute,
    ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Subscript, ast.Slice, ast.Index,
    ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass, ast.IfExp,
    ast.FunctionDef, ast.Return, ast.arguments, ast.arg,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.keyword,
    ast.And, ast.Or, ast.Not, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.MatMult,
    ast.USub, ast.UAdd, ast.BitAnd, ast.BitOr, ast.BitXor, ast.LShift, ast.RShift,
)


def _limited_repr(value: Any, *, max_chars: int = 1200) -> str:
    try:
        text = repr(value)
    except Exception:
        logger.warning("scientific_compute_repr_failed", exc_info=True)
        text = f"<unreprable {type(value).__name__}>"
    text = str(text or "")
    if len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def _result_type_name(value: Any) -> str:
    return type(value).__name__


def _build_env() -> Tuple[Dict[str, Any], List[str]]:
    safe_builtins = {
        "abs": abs,
        "min": min,
        "max": max,
        "sum": sum,
        "sorted": sorted,
        "round": round,
        "len": len,
        "range": range,
        "enumerate": enumerate,
        "zip": zip,
        "all": all,
        "any": any,
        "list": list,
        "tuple": tuple,
        "set": set,
        "dict": dict,
        "float": float,
        "int": int,
        "complex": complex,
        "bool": bool,
        "str": str,
        "print": builtins.print,
    }

    env: Dict[str, Any] = {
        "__builtins__": safe_builtins,
        "math": math,
        "cmath": cmath,
        "statistics": statistics,
        "fractions": fractions,
        "decimal": decimal,
        "Fraction": fractions.Fraction,
        "Decimal": decimal.Decimal,
    }
    warnings: List[str] = []

    try:
        import numpy as np  # type: ignore

        env["np"] = np
    except ImportError:
        warnings.append("numpy_unavailable")

    try:
        import sympy as sp  # type: ignore

        env["sp"] = sp
    except ImportError:
        warnings.append("sympy_unavailable")

    return env, warnings


def _validate_tree(tree: ast.AST) -> None:
    nodes = list(ast.walk(tree))
    if len(nodes) > 800:
        raise ValueError("代码过长或过于复杂")

    for node in nodes:
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise ValueError(f"不允许的语法: {type(node).__name__}")

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("不允许 import；请直接使用预置模块名")

        if isinstance(node, ast.FunctionDef):
            if str(node.name or "").startswith("__"):
                raise ValueError("不允许使用双下划线函数名")
            if list(node.decorator_list or []):
                raise ValueError("不允许使用装饰器")
            if getattr(node, "returns", None) is not None:
                raise ValueError("不允许使用函数返回类型标注")
            args = node.args if isinstance(node.args, ast.arguments) else None
            if args is not None:
                if args.vararg is not None or args.kwarg is not None:
                    raise ValueError("不允许使用 *args 或 **kwargs")
                for arg in list(args.args or []) + list(args.kwonlyargs or []) + list(args.posonlyargs or []):
                    if getattr(arg, "annotation", None) is not None:
                        raise ValueError("不允许使用函数参数类型标注")

        if isinstance(node, ast.Name):
            ident = str(node.id or "")
            if ident.startswith("__"):
                raise ValueError("不允许使用双下划线标识符")

        if isinstance(node, ast.Attribute):
            attr = str(node.attr or "")
            if attr.startswith("__"):
                raise ValueError("不允许访问双下划线属性")

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                func_name = str(node.func.id or "")
                if func_name in _BANNED_CALL_NAMES:
                    raise ValueError(f"不允许调用 {func_name}")


def _compile_code(code: str) -> Tuple[Any, Any]:
    tree = ast.parse(code, mode="exec")
    _validate_tree(tree)
    body = list(tree.body)
    last_expr = None
    if body and isinstance(body[-1], ast.Expr):
        last_expr = ast.Expression(body.pop().value)

    exec_tree = ast.Module(body=body, type_ignores=[])
    ast.fix_missing_locations(exec_tree)
    exec_code = compile(exec_tree, "<python_scientific_compute>", "exec")

    eval_code = None
    if last_expr is not None:
        ast.fix_missing_locations(last_expr)
        eval_code = compile(last_expr, "<python_scientific_compute:last_expr>", "eval")

    return exec_code, eval_code


def _run_code(code: str) -> Dict[str, Any]:
    scope, warnings = _build_env()
    exec_code, eval_code = _compile_code(code)
    stdout_buf = io.StringIO()

    with redirect_stdout(stdout_buf):
        exec(exec_code, scope, scope)
        if "result" in scope:
            result_value = scope.get("result")
        elif eval_code is not None:
            result_value = eval(eval_code, scope, scope)
        else:
            result_value = None

    stdout = stdout_buf.getvalue()
    out: Dict[str, Any] = {
        "success": True,
        "result_repr": _limited_repr(result_value),
        "result_type": _result_type_name(result_value),
        "stdout": stdout[:4000],
        "warnings": warnings,
        "available_names": sorted(
            [name for name in scope.keys() if name not in {"__builtins__", "result"}]
        ),
    }
    return out


def _run_code_isolated(code: str, timeout_seconds: int) -> Dict[str, Any]:
    # File lives under ``backend/integrations/mcp/tools/``, so repo root is 4 levels up.
    repo_root = Path(__file__).resolve().parents[4]
    wrapper = (
        "import json,sys;"
        "from backend.integrations.mcp.tools.python_scientific_compute import _run_code;"
        "src=sys.stdin.read();"
        "res=_run_code(src);"
        "print(json.dumps(res, ensure_ascii=False))"
    )

    try:
        completed = subprocess.run(
            [sys.executable, "-c", wrapper],
            input=code,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=str(repo_root),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"计算超时（>{timeout_seconds}s）"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"success": False, "error": str(exc)}

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        return {"success": False, "error": detail[:1200] or f"worker_exit_{completed.returncode}"}

    try:
        result = json.loads(completed.stdout or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        detail = (completed.stdout or completed.stderr or "").strip()
        return {"success": False, "error": f"invalid_worker_output: {detail[:1200]}"}
    return result if isinstance(result, dict) else {"success": False, "error": "invalid_worker_result"}


async def python_scientific_compute(
    code: str,
    purpose: str = "",
    timeout_seconds: int = 5,
) -> Dict[str, Any]:
    source = str(code or "").strip()
    if not source:
        return {"success": False, "error": "code 不能为空"}
    if len(source) > 6000:
        return {"success": False, "error": "code 过长"}

    timeout = max(1, min(int(timeout_seconds or 5), 15))

    try:
        result = await asyncio.to_thread(_run_code_isolated, source, timeout)
    except Exception as exc:
        logger.warning("scientific_compute_thread_failed", exc_info=True)
        return {"success": False, "error": str(exc), "purpose": str(purpose or "").strip()}

    result["purpose"] = str(purpose or "").strip()
    result["code"] = source
    return result
