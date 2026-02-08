# 7. 静态资源（题面图片与公式资源）

更新时间：2026-02-08

`paper/list` 与 `question/list` 等列表接口返回的是 HTML 片段（`data.html`），题干/选项/材料中常包含 `<img>` 标签引用图片资源（配图、扫描图、公式图等）。本章对以下内容给出可复现的规则描述：

- 题面中常见静态资源域名与路径形态
- 从 HTML 片段中抽取并归一化资源 URL 的规则
- 识别“公式图”并关联到 `.mml`（MathML/Base64）的规则

本章仅描述资源 URL 与数据结构，不包含登录/授权资源的获取方式，也不包含挑战页绕过逻辑。

---

## 7.1 静态资源域名（观测）

在抽样的题块 HTML（`question/list` 的 `data.html`）中，`<img src="...">` 常见域名包括：

- `staticzujuan.xkw.com`
  - 题面图片与公式资源的主要域名（常见路径为 `/quesimg/Upload/...`）。
- `img.xkw.com`
  - 少量富文本编辑器图片或外链图片（路径形态随题目来源变化）。

说明：不同学科、不同题型、不同题源可能出现更多 host；因此 host 清单不构成封闭集合。

---

## 7.2 资源 URL 形态与命名规则

### 7.2.1 公式图片（位图/矢量）

在数学等学科中，题面公式常以图片形式出现。已观察到的典型 URL：

```text
https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.png
https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.svg
```

其中：
- `{hash}` 通常为 32 位十六进制字符串（小写），可作为公式资源的稳定键。
- 扩展名常见：`.png`、`.svg`；也可能出现 `.gif/.jpg`（以实际为准）。

### 7.2.2 公式 MathML sidecar（`.mml`）

对多数公式图片，站点提供同名 `.mml` 文件：

```text
https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.mml
```

`.mml` 的响应体为 Base64 文本；解码后得到 MathML（典型为 `<math>...</math>`）。

与 LaTeX 转换相关的完整链路见：`docs/08-formula-mml-latex.md`。

### 7.2.3 非公式题面图片

除公式外，题块中也常见普通配图/扫描图。其 URL 形态不统一，但在抽样中常落在：

```text
https://staticzujuan.xkw.com/quesimg/Upload/{...}
```

此类图片通常不具备同名 `.mml` 文件。

---

## 7.3 从 HTML 片段抽取资源 URL

### 7.3.1 输入与输出

输入：
- `question/list` 或 `paper/list` 返回的 HTML 片段（`data.html`）。

输出：
- 归一化后的绝对 URL 列表（`https://...`）。

### 7.3.2 `<img src>` 抽取规则

题块中典型的公式图节点示例：

```html
<img src="https://staticzujuan.xkw.com/quesimg/Upload/formula/d275fbb3ee5c....png" style="vertical-align:middle;">
```

抽取规则（按字符串形态分类）：

1) 绝对 URL：`https://host/path`  
直接保留。

2) 协议相对 URL：`//host/path`  
在前面补齐 `https:`，得到 `https://host/path`。

3) 站内绝对路径：`/path`  
该形态在题块片段中相对少见；当路径前缀为 `/quesimg/Upload/` 时，可将其归一化为：

```text
https://staticzujuan.xkw.com{path}
```

对于其它以 `/` 开头的路径，其归属域名需要结合页面上下文判定；本文档不对其做统一归一化承诺。

### 7.3.3 归一化示例（输入 → 输出）

输入片段：

```html
<div class="qbody">
  <img src="//staticzujuan.xkw.com/quesimg/Upload/formula/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png">
  <img src="/quesimg/Upload/2026/02/xx.png">
  <img src="https://img.xkw.com/dksih/QBM/editorImg/2026/02/yy.jpg">
</div>
```

输出（归一化后）：

```text
https://staticzujuan.xkw.com/quesimg/Upload/formula/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png
https://staticzujuan.xkw.com/quesimg/Upload/2026/02/xx.png
https://img.xkw.com/dksih/QBM/editorImg/2026/02/yy.jpg
```

---

## 7.4 识别“公式图”与 `.mml` 关联规则

当抽取到一个图片 URL 后，可用以下规则识别“可尝试 `.mml` 的公式图”：

1) URL 路径包含：`/quesimg/Upload/formula/`
2) 文件名匹配：`{hash}.{ext}`，其中 `{hash}` 为 32 位十六进制字符串

满足上述规则时：
- 公式图片 URL：`.../{hash}.png`（或其它扩展名）
- `.mml` URL：将扩展名替换为 `.mml`，得到 `.../{hash}.mml`

不满足上述规则时，通常不具备同名 `.mml` 文件（以实际返回为准）。

---

## 7.5 静态资源响应头特征（观测）

对 `staticzujuan.xkw.com` 下的图片与 `.mml` 请求，抽样响应头常见：

- `Content-Type: image/png` / `image/jpeg` / `image/gif` / `image/svg+xml`
- `ETag`、`Last-Modified`、`Cache-Control`

这些字段是否出现以及具体语义由服务器与 CDN 配置决定，不构成稳定承诺。

---

## 7.6 Python 片段：抽取并归一化 `<img src>`

以下片段仅演示“抽取 + 归一化规则”的实现（不包含并发、重试、落盘策略）：

```python
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

STATIC_DEFAULT_BASE = "https://staticzujuan.xkw.com"


def normalize_img_src(src: str) -> str | None:
    s = (src or "").strip()
    if not s:
        return None

    if s.startswith("//"):
        return "https:" + s

    if s.startswith("/"):
        # 仅对题面常见的 /quesimg/Upload/ 做归一化示例；其它路径需要结合上下文判定。
        if s.startswith("/quesimg/Upload/"):
            return urljoin(STATIC_DEFAULT_BASE, s)
        return None

    # 绝对 URL
    host = (urlparse(s).hostname or "").lower()
    if host:
        return s
    return None


def extract_img_urls(html_fragment: str) -> list[str]:
    soup = BeautifulSoup(html_fragment, "lxml")
    out: list[str] = []
    for img in soup.select("img[src]"):
        url = normalize_img_src(img.get("src") or "")
        if url:
            out.append(url)
    return out
```
