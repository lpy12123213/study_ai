# 示例：公式图 `.mml`（MathML Base64）解码 + 转 LaTeX + 替换回题干

本示例演示“把题干里的公式图片转成 LaTeX 文本”的最小闭环：

1. 从 HTML 片段里提取公式图 hash（`/Upload/formula/{hash}.png`）
2. 请求同名的 `.mml`（Base64）
3. Base64 解码得到 MathML（XML）
4. 用 `pandoc` 把 MathML 转成 LaTeX
5. 把原来的 `<img ...>` 替换成 `\( ... \)`

前置：
- 你能拿到 `question/list` 的 `data.html`（见 `docs/api/question-list.md`）
- 本机可用 `pandoc`（Windows 常见为 `pandoc.exe`）

> 注意：此处只处理“公式图”（`staticzujuan.xkw.com/.../Upload/formula/`），不处理普通配图/扫描图。

---

## 1) Python：hash -> MathML -> LaTeX（pandoc）

```python
import base64
import re
import subprocess
import urllib.request

FORMULA_IMG_RE = re.compile(
    r"https://staticzujuan\.xkw\.com/quesimg/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg)",
    re.I,
)

FORMULA_IMG_TAG_RE = re.compile(
    r'<img[^>]+src=["\']https://staticzujuan\.xkw\.com/quesimg/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg)["\'][^>]*>',
    re.I,
)


def fetch_mathml_xml(formula_hash: str) -> str:
    # `.mml` response body is base64 of MathML XML
    url = f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{formula_hash}.mml"
    raw = urllib.request.urlopen(url, timeout=30).read().strip()
    return base64.b64decode(raw).decode("utf-8")


def mathml_to_latex_via_pandoc(mathml_xml: str) -> str:
    # pandoc reads MathML from HTML input and outputs LaTeX.
    p = subprocess.run(
        ["pandoc", "-f", "html", "-t", "latex"],
        input=mathml_xml,
        text=True,
        encoding="utf-8",  # Windows 默认编码可能为 GBK/cp936；显式指定 UTF-8 可避免编码异常
        capture_output=True,
        check=True,
    )
    return p.stdout.strip()


def formula_hash_to_latex(formula_hash: str) -> str:
    mathml_xml = fetch_mathml_xml(formula_hash)
    return mathml_to_latex_via_pandoc(mathml_xml)


def latexify_html_fragment(html_fragment: str) -> str:
    # 1) collect hashes
    hashes = []
    seen = set()
    for m in FORMULA_IMG_RE.finditer(html_fragment):
        h = m.group(1).lower()
        if h not in seen:
            seen.add(h)
            hashes.append(h)

    # 2) convert with cache (in-memory demo)
    cache = {}
    for h in hashes:
        try:
            cache[h] = formula_hash_to_latex(h)
        except Exception:
            # network / pandoc fail -> keep image tag
            cache[h] = None

    # 3) replace <img ... formula/{hash}.png ...> -> latex
    def repl(m: re.Match) -> str:
        h = m.group(1).lower()
        latex = cache.get(h)
        return latex if latex else m.group(0)

    return FORMULA_IMG_TAG_RE.sub(repl, html_fragment)
```

---

## 2) 小测试：把一个公式 hash 转成 LaTeX

```python
print(formula_hash_to_latex("b0ce3733e15305fdd37636106caccc5a"))
# 期望输出类似：\(f(x) = x^{3} + x + 1\)
```

更完整的原理与边界见：
- `docs/08-formula-mml-latex.md`
