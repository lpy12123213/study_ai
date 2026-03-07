from __future__ import annotations

import re


FORMULA_HASH_PATTERN = re.compile(r"/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg|svg)", re.IGNORECASE)
FORMULA_IMG_TAG_PATTERN = re.compile(
    r'<img\b[^>]*\bsrc\s*=\s*(?P<q>[\'"])(?P<src>[^\'"]*/Upload/formula/(?P<hash>[0-9a-f]{32})\.(?:png|gif|jpg|svg)(?:\?[^\'"]*)?)(?P=q)[^>]*>',
    re.IGNORECASE,
)
IMG_TAG_PATTERN = re.compile(
    r'<img\b[^>]*\bsrc\s*=\s*(?P<q>[\'"])(?P<src>[^\'"]+)(?P=q)[^>]*>',
    re.IGNORECASE,
)
