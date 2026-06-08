"""Sandboxed expression evaluator used by plotting helpers.

Pulled out of the plotting modules so the safety-critical AST
validation logic has a focused module + can be unit-tested without spinning
up matplotlib. The validator only allows a small subset of Python operators
and named functions (sin/cos/sqrt/...) — no attribute access beyond ``np.*``
constants, no calls outside the whitelist, and no keyword arguments.
"""

from __future__ import annotations

import ast
from typing import Any, Dict, FrozenSet, Tuple, Type

_ALLOWED_FUNCS: FrozenSet[str] = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "exp",
        "log",
        "ln",
        "log10",
        "sqrt",
        "abs",
        "floor",
        "ceil",
        "sign",
    }
)

_ALLOWED_NAMES: FrozenSet[str] = frozenset({"x", "y", "pi", "e", "np", *_ALLOWED_FUNCS})

_ALLOWED_NODES: Tuple[Type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.Attribute,
)


class _ExprValidator(ast.NodeVisitor):
    """AST visitor that rejects anything outside the whitelist."""

    def visit(self, node: ast.AST):  # noqa: D401 – override
        if not isinstance(node, _ALLOWED_NODES):
            raise ValueError("unsupported_expr")
        return super().visit(node)

    def visit_Name(self, node: ast.Name):  # noqa: N802 – ast convention
        if node.id not in _ALLOWED_NAMES:
            raise ValueError("unsupported_name")
        return None

    def visit_Attribute(self, node: ast.Attribute):  # noqa: N802 – ast convention
        if not isinstance(node.value, ast.Name) or node.value.id != "np":
            raise ValueError("unsupported_attr")
        if node.attr not in _ALLOWED_FUNCS and node.attr not in {"pi", "e"}:
            raise ValueError("unsupported_attr")
        return None

    def visit_Call(self, node: ast.Call):  # noqa: N802 – ast convention
        fn = node.func
        if isinstance(fn, ast.Name):
            if fn.id not in _ALLOWED_FUNCS:
                raise ValueError("unsupported_call")
        elif isinstance(fn, ast.Attribute):
            self.visit_Attribute(fn)
        else:
            raise ValueError("unsupported_call")

        if node.keywords:
            raise ValueError("unsupported_call")

        for a in node.args:
            self.visit(a)
        return None


def safe_eval_expr(expr: str, *, variables: Dict[str, Any]) -> Any:
    """Evaluate ``expr`` against the whitelist + numpy environment.

    ``variables`` is merged on top of the default environment so callers can
    expose ``x`` / ``y`` arrays from the plotting pipeline.
    """

    raw = str(expr or "").strip()
    if not raw:
        raise ValueError("empty_expr")
    raw = raw.replace("^", "**")
    tree = ast.parse(raw, mode="eval")
    _ExprValidator().visit(tree)

    import numpy as np  # local import keeps module load cheap when matplotlib is not used

    env: Dict[str, Any] = {
        "np": np,
        "pi": float(np.pi),
        "e": float(np.e),
        "sin": np.sin,
        "cos": np.cos,
        "tan": np.tan,
        "asin": np.arcsin,
        "acos": np.arccos,
        "atan": np.arctan,
        "sinh": np.sinh,
        "cosh": np.cosh,
        "tanh": np.tanh,
        "exp": np.exp,
        "log": np.log,
        "ln": np.log,
        "log10": np.log10,
        "sqrt": np.sqrt,
        "abs": np.abs,
        "floor": np.floor,
        "ceil": np.ceil,
        "sign": np.sign,
    }
    env.update(variables)
    return eval(  # noqa: S307 – validator above restricts the AST
        compile(tree, "<expr>", "eval"),
        {"__builtins__": {}},
        env,
    )


__all__ = ["safe_eval_expr"]
