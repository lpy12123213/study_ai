# API: `GET /zujuan-api/base`（基础枚举：学段/学科库/题型等）

更新时间：2026-02-08

## 1) 基本信息

- 方法：`GET`
- URL：`https://zujuan.xkw.com/zujuan-api/base`
- 认证：访客态可用（不要求登录）
- 响应 `Content-Type`（抽样）：`text/plain; charset=utf-8`
- 响应体类型：JavaScript 变量文本（不是纯 JSON）

用途（语义层面）：
- 获取“学段 → 学科库（bankId）→ 题型/题目属性/年级/卷型等”枚举结构（字段集合以实际返回为准）。
- 获取 `courseId` 与路由前缀 `courseIdPy`（例如 `gzsx`）。
- 获取 `cdn_domain`（用于 CDN tree 等静态资源入口）。

相关文档：
- `docs/01-identifiers-and-urls.md`
- `docs/03-entrypoints-cdn-tree.md`

---

## 2) 请求

### 2.1 Query 参数

无。

### 2.2 请求头（观测到的敏感点）

抽样观察到：该端点对 `User-Agent` 形态敏感。

- 当 UA 为浏览器形态时，通常返回完整的 `var edu=[...]` 文本。
- 当 UA 过于“脚本化”（例如默认 `Python-urllib/...`）时，可能返回与业务无关的短文本占位（示例：`welcome to imworld`）。

因此，判定“拿到目标枚举数据”应以响应体是否包含 `var edu=` 为准，而不应仅以 HTTP 状态码为准。

---

## 3) 响应结构（示例）

响应体常以 `var edu=` 开头，随后是一个 JSON 数组（示例截断，仅示意形态）：

```js
var edu=[{"ID":1,"Name":"小学","QuesBankList":[{"ID":24,"Name":"小学语文",...}]} ...]
```

同一响应体中通常还包含其它变量与站点配置片段（示例截断）：

```text
...,cdn_domain='https://static.zxxk.com',v2_cdn_path='https://static.zxxk.com/zujuan',...
```

说明（字段以实际返回为准）：
- `edu`：学段列表。
- `edu[].QuesBankList[]`：学科库列表（每个学段下多个学科库）。其中：
  - `QuesBankList[].ID`：`bankId`
  - `QuesBankList[].courseId`：`courseId`
  - `QuesBankList[].courseIdPy`：`courseIdPy`
  - `QuesBankList[].QuesTypeList[]`：题型枚举（常用于 `question/list` 的题型过滤）

---

## 4) 解析方法（从变量文本提取结构化数据）

该端点返回的是“一个很长的变量赋值文本”，常见形态为：

```text
var edu=[...],diffs=[...],...,cdn_domain='...'
```

其中可能缺少分号，且包含字符串字面量与嵌套数组/对象。因此解析时通常采用“按变量名定位，再做括号配对截取”的方式。

### 4.1 Python 示例：截取并解析 `edu=[...]`

```python
import json


def extract_bracket_array(text: str, var_name: str) -> str:
    # /zujuan-api/base is usually like:
    #   var edu=[...],diffs=[...],... ,cdn_domain='...'
    # i.e. one huge "var" statement without semicolons.
    marker = f"{var_name}="
    idx = text.find(marker)
    if idx < 0:
        raise ValueError(f"{var_name} not found")

    start = text.find("[", idx)
    if start < 0:
        raise ValueError(f"{var_name} has no '['")

    depth = 0
    in_str = False
    esc = False
    quote = ""
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\\\":
                esc = True
            elif ch == quote:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                quote = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        i += 1

    raise ValueError(f"unbalanced brackets for {var_name}")


def parse_base_edu(text: str):
    edu_json = extract_bracket_array(text, "edu")
    return json.loads(edu_json)
```

### 4.2 提取 `cdn_domain`（字符串变量）

`cdn_domain` 在响应尾部常以如下形式出现：

```text
cdn_domain='https://static.zxxk.com'
```

实现侧可按字符串搜索或正则提取其值。`cdn_domain` 的用途见：`docs/03-entrypoints-cdn-tree.md`。
