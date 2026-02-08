# 从 HTML 中抽取内嵌 JS 变量（不执行 JS）

很多 zujuan 页面会把结构化数据直接写在 `<script>` 里，例如：
- 试卷页：`var paper = {...};`、`var paperJson = {...};`
- 试题页：`window.quesDetal.quesid = 31298690;`

安全边界：本文档集将页面脚本视为不可信输入，仅进行文本抽取与解析；不执行脚本代码。

## 1) 花括号配对：抽 `var paper = {...}` / `var paperJson = {...}`

思路：
- 先定位 `var paper =` 的起点
- 找到第一个 `{`
- 从这个 `{` 开始做花括号配对，直到配对结束的 `}`
- 截出来的 `{...}` 再尝试 `json.loads`

注意：
- 有些对象不是严格 JSON（可能含 `true/false`、尾逗号等），`json.loads` 会失败
- 当对象文本无法被 `json.loads` 解析时，可将原始对象文本作为原始数据保留（结构化字段缺省）。

Python 示例（最小实现，适合 paper/paperJson 这种基本 JSON 兼容的对象）：

```python
import json

def extract_braced_object(text: str, start_pos: int) -> tuple[str, int]:
    # start_pos points to the first '{'
    depth = 0
    i = start_pos
    in_str = False
    str_quote = ""
    escape = False

    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == str_quote:
                in_str = False
        else:
            if ch in ("\"", "'"):
                in_str = True
                str_quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start_pos : i + 1], i + 1
        i += 1

    raise ValueError("unbalanced braces")


def extract_var_object(html: str, var_name: str):
    marker = f"var {var_name}"
    idx = html.find(marker)
    if idx < 0:
        return None
    brace = html.find("{", idx)
    if brace < 0:
        return None
    obj_text, end_pos = extract_braced_object(html, brace)
    return obj_text


def parse_json_best_effort(obj_text: str):
    try:
        return json.loads(obj_text)
    except Exception:
        return None
```

## 2) 正则：抽 `window.quesDetal.*`（试题页）

试题详情页常见片段：

```html
<script>
  window.quesDetal={};
  window.quesDetal.status = 0;
  window.quesDetal.quesid = 31298690;
  window.quesDetal.userid = 0;
</script>
```

Python 示例：

```python
import re

def extract_ques_detal(html: str):
    m = re.search(r"window\.quesDetal\.quesid\s*=\s*(\d+)", html)
    quesid = int(m.group(1)) if m else None

    m = re.search(r"window\.quesDetal\.userid\s*=\s*(\d+)", html)
    userid = int(m.group(1)) if m else None

    m = re.search(r"window\.quesDetal\.status\s*=\s*(\d+)", html)
    status = int(m.group(1)) if m else None

    return {"quesid": quesid, "userid": userid, "status": status}
```

## 3) 变量与字段（观测）

- 试卷页常见变量：
  - `paper`：试卷元信息（标题、年级、地区、卷型、题数等字段；字段集合以页面为准）
  - `paperJson`：题型分组与题目列表（题号、题目 ID 等字段；字段集合以页面为准）
- 试题页常见变量：
  - `window.quesDetal`：访客态/用户态相关字段（例如 `userid=0`）
