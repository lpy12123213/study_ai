from __future__ import annotations

import ast


class UnsafeManimCodeError(ValueError):
    """Raised when generated Manim code fails the structural safety gate."""


_MAX_CODE_CHARS = 80_000
_MAX_AST_NODES = 8_000


def validate_manim_code(code: str, *, scene_name: str) -> None:
    """Validate only structure and bounded size.

    Generated code is intentionally not filtered by content words, imports, or
    call names. It is treated as untrusted and executed only inside the Docker
    sandbox; this gate merely catches malformed output before paying render cost.
    """

    src = str(code or "")
    if not src.strip():
        raise UnsafeManimCodeError("empty_code")
    if len(src) > _MAX_CODE_CHARS:
        raise UnsafeManimCodeError("code_too_large")

    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        raise UnsafeManimCodeError(f"syntax_error:{exc.msg}") from exc

    scene = str(scene_name or "").strip()
    if not scene.isidentifier():
        raise UnsafeManimCodeError("invalid_scene_name")

    found_scene = False
    node_count = 0
    for node in ast.walk(tree):
        node_count += 1
        if node_count > _MAX_AST_NODES:
            raise UnsafeManimCodeError("code_too_complex")

        if isinstance(node, ast.ClassDef) and node.name == scene:
            found_scene = True

    if not found_scene:
        raise UnsafeManimCodeError("scene_class_not_found")
