# 8. 公式资源：从公式图片获取 MathML 与 LaTeX（访客态）

更新时间：2026-02-08

在 zujuan.xkw.com 的题面 HTML 中，数学公式常见表现形式为“公式图片”（`<img>`），而非 LaTeX 文本。对这类公式图片，站点的静态资源域名通常同时提供：

- 同名 `.mml` 文件（Base64 编码的 MathML）
- 同名 `.svg` 文件（矢量版本，便于高清展示）

本章以“可复现的输入/输出规则”说明：
- 如何从题块 HTML 中定位公式图片并提取 `{hash}`
- 如何通过 `{hash}.mml` 获得 MathML（Base64 解码）
- 如何将 MathML 转换为 LaTeX（以 pandoc 为例）
- 如何在题块 HTML 中替换公式 `<img>` 得到 LaTeX 化题面

范围边界：
- 本章只涉及公开可访问的静态资源（`staticzujuan.xkw.com`）与公开列表接口返回的题块 HTML。
- 不包含任何登录/会员/验证码/挑战页的绕过逻辑。

相关文档：
- `docs/api/question-list.md`：获取题块 HTML（`data.html`）
- `docs/07-static-assets.md`：题面图片与公式资源 URL 规则
- `docs/10-question-fragment-to-json.md`：从题块 HTML 抽取字段（含公式 hash）
- `docs/examples/formula-coverage-probe.py`：覆盖率抽样脚本

---

## 8.1 题块 HTML 的获取位置（输入）

在访客态（不登录）条件下，`POST /zujuan-api/question/list` 返回 JSON，其中 `data.html` 为题目列表的 HTML 片段。该片段通常已经包含题干与选项，并直接包含公式 `<img>`。

题块示例（截断，仅示意公式图片形态）：

```html
<div class="tk-quest-item" questionid="31205079">
  <div class="qbody">
    设函数
    <img src="https://staticzujuan.xkw.com/quesimg/Upload/formula/b0ce3733e15305fdd37636106caccc5a.png">
    ...
  </div>
</div>
```

---

## 8.2 公式图片 URL 与 `{hash}` 规则

### 8.2.1 公式图片 URL 模式（观测）

公式图片常见 URL 模式：

```text
https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.png
```

其中 `{hash}` 的可观察特征：
- 长度为 32
- 字符集为十六进制（`[0-9a-f]`），通常为小写

### 8.2.2 `{hash}` 的提取

可使用以下正则从题块 HTML 中提取 `{hash}`（大小写不敏感）：

```regex
https://staticzujuan\.xkw\.com/quesimg/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg|svg)
```

说明：
- 扩展名集合以实际观测为准；样例中最常见为 `.png`。
- `{hash}` 可作为公式资源的主键。

---

## 8.3 `.mml`（MathML sidecar）：请求与解码

### 8.3.1 `.mml` URL 构造

对任意公式 hash：

```text
{hash}.mml = https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.mml
```

同目录下还常见：

```text
{hash}.svg = https://staticzujuan.xkw.com/quesimg/Upload/formula/{hash}.svg
```

### 8.3.2 `.mml` 响应体格式（观测）

对抽样的 `.mml` 请求，响应具有以下可观察特征：
- `Content-Type` 常见为 `application/mml`（以实际返回为准）
- 响应体不是 `<math>...</math>` 明文，而是 Base64 文本
- Base64 解码后得到 MathML（XML），典型以 `<math>` 根元素开头

示例（MathML，截断）：

```xml
<math>
  <mrow>
    <mi>f</mi>
    <mo stretchy="false">(</mo><mi>x</mi><mo stretchy="false">)</mo>
    <mo>=</mo>
    <msup><mi>x</mi><mn>3</mn></msup>
    <mo>+</mo><mi>x</mi><mo>+</mo><mn>1</mn>
  </mrow>
</math>
```

### 8.3.3 cURL 示例（获取 Base64）

```bash
curl.exe -s "https://staticzujuan.xkw.com/quesimg/Upload/formula/b0ce3733e15305fdd37636106caccc5a.mml"
```

### 8.3.4 Python 示例（Base64 解码为 MathML）

```python
import base64
import urllib.request

url = "https://staticzujuan.xkw.com/quesimg/Upload/formula/b0ce3733e15305fdd37636106caccc5a.mml"
raw_b64 = urllib.request.urlopen(url, timeout=30).read().strip()
mathml_xml = base64.b64decode(raw_b64).decode("utf-8")
print(mathml_xml)
```

编码说明（Windows）：
- `.mml` 解码后的 MathML 在抽样中可按 UTF-8 文本解码。
- 在 Python 调用外部工具（例如 pandoc）时，需要显式指定 `encoding="utf-8"`（见 8.4.2）。

---

## 8.4 MathML → LaTeX（以 pandoc 为例）

本仓库示例脚本使用 pandoc 将 MathML（作为 HTML 输入的一部分）转换为 LaTeX。

### 8.4.1 命令行示例

```bash
echo "<math><mrow><mi>x</mi><mo>=</mo><mn>1</mn></mrow></math>" | pandoc -f html -t latex
```

输出示例：

```text
\(x = 1\)
```

### 8.4.2 Python（subprocess）示例

```python
import subprocess

def mathml_to_latex_via_pandoc(mathml_xml: str) -> str:
    p = subprocess.run(
        ["pandoc", "-f", "html", "-t", "latex"],
        input=mathml_xml,
        text=True,
        encoding="utf-8",  # Windows 默认编码可能为 GBK/cp936；显式指定 UTF-8 可避免编码异常
        capture_output=True,
        check=True,
    )
    return p.stdout.strip()
```

Windows 常见编码异常（症状）：

```text
'gbk' codec can't encode character '\\u2212' ...
```

该错误对应的可观察原因是：Python 在 `text=True` 时使用系统默认编码对 stdin 编码；当输入包含 U+2212（减号）等字符时，默认编码无法表示。

---

## 8.5 在题块 HTML 中替换公式 `<img>`（输出）

### 8.5.1 输入与输出定义

输入：
- `raw_html_fragment`：原始题块 HTML（包含公式 `<img ...formula/{hash}.png...>`）
- `hash -> latex` 映射（来自 8.3 与 8.4）

输出：
- `latex_html_fragment`：将可转换的公式 `<img>` 替换为 LaTeX 文本后的题块 HTML（LaTeX 形式通常为 `\\( ... \\)`）

### 8.5.2 替换规则（可复现口径）

替换口径示例：
- 对每个匹配到的公式图片 URL（含 `{hash}`），在 HTML 中定位对应的 `<img>` 节点。
- 将该 `<img>` 节点替换为 LaTeX 字符串（例如 `\\(f(x)=x^3+x+1\\)`）。

说明：
- 替换可按 DOM 节点级别进行（HTML 解析器），也可按字符串级别进行（需控制误匹配）。
- 当某个 `{hash}` 无法获得 `.mml` 或无法成功转换时，该 `{hash}` 不产生 LaTeX；是否替换为占位文本由实现方定义。

---

## 8.6 覆盖率抽样结果（本机实测）

本仓库提供脚本 `docs/examples/formula-coverage-probe.py`，对 `question/list` 返回片段中的公式 hash 进行抽样验证，覆盖以下环节：

- `.mml` HTTP 获取（状态码与响应体）
- Base64 解码
- 解码后 `<math>` 结构存在性
- pandoc 转换（本机已安装 pandoc 时）

在 2026-02-08 的一次样例运行中（脚本日志记录的参数为 `pageName=zsd&categoryId=28102`）：
- `unique_hashes=152`
- 抽样 `sample_size=100`
- `.mml` 获取成功：100/100
- Base64 解码成功：100/100
- `<math>` 检测通过：100/100
- pandoc 转换成功：100/100

脚本输出格式与命令行参数见脚本文件注释。

---

## 8.7 常见异常与原因（不包含绕过）

| 现象 | 可观察特征 | 常见原因类别 |
|---|---|---|
| `.mml` 返回 404 | HTTP 404 | 该 `{hash}` 无对应 `.mml`（以实时为准） |
| `.mml` 返回非 Base64 | 响应体无法 Base64 解码 | 响应被替换为 HTML/错误页，或资源内容异常 |
| Base64 解码后不含 `<math>` | 解码文本不含 `<math` | 内容格式非预期（站点变更或异常内容） |
| pandoc 未找到 | `FileNotFoundError` / 返回码非 0 | 本机未安装 pandoc，或环境变量不可见 |
| Windows 编码报错 | `gbk codec can't encode ...` | subprocess stdin 使用默认编码导致不可表示字符 |

当出现挑战页/登录页等非目标响应时，响应体通常为 HTML；挑战页特征见 `docs/02-session-cookies-headers.md` 与 `docs/troubleshooting.md`。
