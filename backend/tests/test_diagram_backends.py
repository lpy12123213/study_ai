from __future__ import annotations

import asyncio
import shutil
import unittest
from unittest.mock import patch

from backend.generation.question_library.diagram_utils import render_asy_to_url
from backend.generation.question_library.diagram_utils import render_svg_to_url


class TestDiagramBackends(unittest.TestCase):
    def test_render_svg_cache_key_is_user_scoped(self) -> None:
        seen_hashes: list[str] = []

        async def fake_lookup(spec_hash: str):
            seen_hashes.append(spec_hash)
            return None

        async def fake_record(*_args, **_kwargs):
            return None

        async def fake_publish(data: bytes, *, user_id: str, ext: str, file_type: str, mime_type: str, ttl_s: int):
            return {
                "url": f"/api/media/generated/{user_id}.svg",
                "filename": f"{user_id}.svg",
                "sha256": user_id,
                "bytes": len(data),
            }

        with patch("backend.generation.question_library.diagram_utils.cache_lookup", new=fake_lookup):
            with patch("backend.generation.question_library.diagram_utils.cache_record", new=fake_record):
                with patch("backend.generation.question_library.diagram_utils.publish_generated_bytes", new=fake_publish):
                    with patch("backend.core.svg_diagram.render_svg_diagram", return_value="<svg></svg>"):
                        asyncio.run(render_svg_to_url(spec={"shape": "circle"}, user_id="user-a", alt="diagram"))
                        asyncio.run(render_svg_to_url(spec={"shape": "circle"}, user_id="user-b", alt="diagram"))

        self.assertEqual(len(seen_hashes), 2)
        self.assertNotEqual(seen_hashes[0], seen_hashes[1])

    @unittest.skipUnless(shutil.which("asy") is not None, "asy not installed")
    def test_render_asy_to_url_publishes_svg(self) -> None:
        # Keep the program minimal to reduce external tool latency.
        asy_code = "size(160); draw((0,0)--(1,0)--(1,1)--cycle);"
        res = asyncio.run(render_asy_to_url(asy=asy_code, user_id="unittest", alt="diagram"))
        self.assertIsInstance(res, dict)
        if not bool(res.get("success")):
            # On some Windows environments (fresh MiKTeX install or sandboxed execution),
            # `asy` can exist on PATH but still be unusable. Skip to keep CI green when
            # TeX toolchains are intentionally absent.
            err = str(res.get("error") or "")
            if any(
                marker in err
                for marker in [
                    "svg_missing",
                    "fresh TeX installation",
                    "finish the setup",
                    "Access is denied",
                    "拒绝访问",
                ]
            ):
                raise unittest.SkipTest(f"asy toolchain not usable: {err[:180]}")
            self.fail(str(res))

        url = str(res.get("url") or "")
        self.assertIn("/api/media/generated/", url)

        filename = str(res.get("filename") or "")
        self.assertTrue(filename.endswith(".svg"), filename)
