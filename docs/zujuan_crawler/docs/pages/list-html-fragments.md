# 页面片段：`paper/list` 与 `question/list` 的 `data.html` 结构与抽取点

更新时间：2026-02-08

`POST /zujuan-api/paper/list` 与 `POST /zujuan-api/question/list` 的共同点：
- 返回 JSON
- 主要业务内容位于 `data.html`（HTML 片段字符串）
- 片段中大量出现相对路径（例如 `/11p3044139.html`），需要在解析侧补全为绝对 URL

本章给出“抽取点”（extract points）与常见正则模式，用于从片段中抽取 ID 与核心字段。

---

## 1) `paper/list` 片段：`paperId` 抽取

### 1.1 主要抽取点

试卷链接常以如下模式出现：

```text
/{bankId}p{paperId}.html
```

### 1.2 正则样例

```regex
/(\\d+)p(\\d+)\\.html
```

捕获组含义：
- group(1)：`bankId`
- group(2)：`paperId`

### 1.3 片段内常见可观察字段

不同列表样式下 DOM 结构可能不同，但常见信息包括：
- 试卷标题（常位于 `<a ... title="...">` 或 `<a ...>文本</a>`）
- 卷型/分类标签（常见 `type-name` 等 class）
- 题量、浏览量等计数（页面展示文本中出现）
- 按钮/控件的 `data-*` 属性（例如 `data-paperid/data-bankid`）

文本字段可能包含 HTML 实体编码（例如 `&#x540C;&#x6B65;`），若需要抽取纯文本，可先进行实体解码（见第 3 节）。

---

## 2) `question/list` 片段：`questionId` 抽取

### 2.1 主要抽取点

题块根节点常包含：

```text
questionid="31236198"
```

### 2.2 正则样例

```regex
questionid="(\\d+)"
```

补充：题块中也可能出现题目详情链接：

```text
/{bankId}q{questionId}.html
```

---

## 3) HTML 实体解码（用于文本字段）

`data.html` 中常出现 `&#x....;` 形式的实体编码。若需要抽取标题、地区、题型名称等“纯文本字段”，可进行实体解码。

Python 示例：

```python
import html

decoded = html.unescape(raw_html_fragment)
```

说明：实体解码不会改变 DOM 属性字段（例如 `questionid="..."`），但会影响基于文本节点的解析结果。
