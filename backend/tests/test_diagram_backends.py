from __future__ import annotations

import asyncio
import shutil
import unittest

from backend.question_library.diagram_utils import render_asy_to_url


class TestDiagramBackends(unittest.TestCase):
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
