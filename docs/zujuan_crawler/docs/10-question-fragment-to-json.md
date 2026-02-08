# 10. `question/list` 返回片段的结构化解析（HTML → 字段）

更新时间：2026-02-08

`POST /zujuan-api/question/list` 返回 JSON，但核心业务数据位于 `data.html`（HTML 片段）。该片段包含一组“题块”（每题一个根节点），并在题块中嵌入题干、选项、题源链接、知识点/方法标签等信息。

本章给出：
- `data.html` 的输入形态
- 题块根节点的定位规则
- 常见字段的抽取位置与字段语义
- 公式资源 hash 的抽取规则（用于 `.mml`/LaTeX 链路）

范围：
- 访客态（不登录）
- 以 `question/list` 返回片段作为主要题面来源

相关文档：
- `docs/api/question-list.md`：接口参数与返回结构
- `docs/pages/list-html-fragments.md`：列表片段整体结构与分隔
- `docs/08-formula-mml-latex.md`：公式图片 → `.mml`（MathML/Base64）→ LaTeX
- `docs/09-output-contract.md`：产物 JSON 字段定义（本仓库口径）

---

## 10.1 输入（API 返回的 JSON）

典型响应结构（截断，仅示意）：

```json
{
  "code": "0",
  "data": {
    "html": "<div class=\"tk-quest-item ...\" questionid=\"31205079\">...</div> ...",
    "total": 360904
  }
}
```

结构化解析的输入为：
- `payload["data"]["html"]`（字符串）

---

## 10.2 题块根节点（单题切分）

在抽样的 `data.html` 中，每道题通常以如下 `div` 作为根节点：

```html
<div class="tk-quest-item quesroot"
     questionindex="0"
     questionid="31205079"
     bankid="11">
  ...
</div>
```

根节点属性字段（抽样中可用）：
- `questionid`：试题 ID（`question_id`）
- `bankid`：学科题库 ID（`bank_id`）
- `questionindex`：该题在当前分页返回中的序号（可作为展示序号或排序辅助）

题块切分规则（CSS 选择器表达）：

```text
div.tk-quest-item[questionid]
```

---

## 10.3 常见字段：抽取位置与语义

本节描述的字段均为“基于页面片段可观察到的字段”，不构成稳定协议承诺；字段的存在性与 DOM 结构可能随站点调整。

### 10.3.1 题型/难度/分类提示（按钮属性）

题块的操作区域常见“加入试题篮”按钮，其属性携带题型/难度等结构化信息：

```html
<a class="addques ..."
   quesid="31305661"
   qyid="2703" qyname="解答题"
   qdid="3" qdname="适中"
   categoryId="28321" categoryName="三角函数"
>加入试题篮</a>
```

可映射字段（示例）：
- `meta.ques_type.id` ← `qyid`
- `meta.ques_type.name` ← `qyname`
- `meta.ques_diff.id` ← `qdid`
- `meta.ques_diff.name` ← `qdname`
- `meta.category_hint.id` ← `categoryId`
- `meta.category_hint.name` ← `categoryName`

说明：
- `meta.category_hint` 来自题块内部提示属性，其语义不必然等同于调用 `question/list` 时所使用的 `categoryId`（两者属于不同语境的“分类”）。

### 10.3.2 题源（来源试卷）

题块顶部常见题源链接：

```html
<a href="/11p3034944.html" class="addi-msg ques-src">25-26高一上·江苏扬州·期末</a>
```

可抽取字段：
- `links.source_paper_url`：补全为绝对 URL，例如 `https://zujuan.xkw.com/11p3034944.html`
- `meta.source_paper_id`：从 `/11p(\\d+).html` 解析出 `paperId`

### 10.3.3 知识点（zsd）与解题方法（jtff）链接

知识点链接示例：

```html
<a href="/course27/zsd28102/" class="knowledge-item">函数周期性的应用</a>
```

解题方法链接示例：

```html
<a class="item" href="/course27/jtff149446">利用周期性求函数值</a>
```

可抽取字段（示例）：
- `tags.knowledge_zsd_ids`：从 `.../zsd(\\d+)` 抽取 ID
- `tags.method_jtff_ids`：从 `.../jtff(\\d+)` 抽取 ID

说明：题块中也可能出现其它类型的标签链接（例如包含 `tre` 等片段的路由）；此类链接的分类口径尚未在本文档集中完成映射，宜保留其原始 `href/text` 以便后续对齐（见 `docs/15-next-exploration.md`）。

### 10.3.4 题干/选项 HTML（题面内容）

题干与选项常位于题块内部的内容容器中，例如：

```html
<div class="wrapper quesdiv" id="quesdiv31205079">
  <div class="exam-item__cnt"> ...题干/选项... </div>
</div>
```

产物层面常见两种保留粒度：
- 题块根节点的 `outerHTML`（包含属性、标签与部分元信息）
- `exam-item__cnt` 的 `innerHTML`（体积更小，但上下文信息更少）

---

## 10.4 公式 hash 抽取（用于 `.mml`/LaTeX 链路）

题块中的公式常以图片形式出现：

```html
<img src="https://staticzujuan.xkw.com/quesimg/Upload/formula/d275fbb3ee5cd1177ca5a2ceecbbef0f.png">
```

可使用如下正则从题块 HTML 中提取 `{hash}`：

```regex
/Upload/formula/([0-9a-f]{32})\.(png|gif|jpg|svg)
```

得到 `{hash}` 后，可按 `docs/08-formula-mml-latex.md` 中的规则构造 `{hash}.mml` 并获取 MathML。

---

## 10.5 Python 示例：解析 `data.html` 为结构化 dict

以下示例仅覆盖常见字段，并以“字段存在性优先”的方式编写；当某字段不存在时返回 `None` 或空列表。

```python
import html as html_lib
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://zujuan.xkw.com"

RE_PAPER = re.compile(r"/(\\d+)p(\\d+)\\.html")
RE_ZSD = re.compile(r"/course(\\d+)/zsd(\\d+)(/|$)")
RE_JTFF = re.compile(r"/course(\\d+)/jtff(\\d+)(/|$)")
RE_FORMULA_HASH = re.compile(r"/Upload/formula/([0-9a-f]{32})\\.(png|gif|jpg|svg)", re.I)


def parse_question_list_fragment(html_fragment: str):
    decoded = html_lib.unescape(html_fragment)
    soup = BeautifulSoup(decoded, "lxml")
    out = []

    for root in soup.select("div.tk-quest-item[questionid]"):
        qid = int(root.get("questionid"))
        bank_id = int(root.get("bankid") or 0) or None
        qindex = int(root.get("questionindex") or 0)

        # 题源试卷
        src_a = root.select_one("a.ques-src[href]")
        source_paper_url = urljoin(BASE, src_a["href"]) if src_a else None
        source_paper_id = None
        if src_a:
            m = RE_PAPER.search(src_a["href"])
            if m:
                source_paper_id = int(m.group(2))

        # 详情页（若题块提供）
        detail_a = root.select_one("a.detail[href]")
        detail_url = urljoin(BASE, detail_a["href"]) if detail_a else None

        # 按钮属性（题型/难度/分类提示）
        add_btn = root.select_one("a.addques[quesid]")
        meta = {}
        if add_btn:
            meta["ques_type"] = {"id": int(add_btn.get("qyid") or 0), "name": add_btn.get("qyname") or ""}
            meta["ques_diff"] = {"id": int(add_btn.get("qdid") or 0), "name": add_btn.get("qdname") or ""}
            meta["category_hint"] = {"id": int(add_btn.get("categoryid") or 0), "name": add_btn.get("categoryname") or ""}

        # 标签链接（知识点/方法）
        zsd_ids = []
        jtff_ids = []
        other_links = []
        for a in root.select("a[href]"):
            href = a.get("href") or ""

            m = RE_ZSD.search(href)
            if m:
                zsd_ids.append(int(m.group(2)))
                continue

            m = RE_JTFF.search(href)
            if m:
                jtff_ids.append(int(m.group(2)))
                continue

            if "tre" in href:
                other_links.append({"href": href, "text": a.get_text(strip=True)})

        # 公式 hash（去重）
        formula_hashes = [h for (h, _ext) in RE_FORMULA_HASH.findall(str(root))]
        formula_hashes = sorted(set([h.lower() for h in formula_hashes]))

        out.append(
            {
                "bank_id": bank_id,
                "question_id": qid,
                "question_index": qindex,
                "links": {
                    "detail_url": detail_url,
                    "source_paper_url": source_paper_url,
                },
                "meta": meta,
                "tags": {
                    "knowledge_zsd_ids": sorted(set(zsd_ids)),
                    "method_jtff_ids": sorted(set(jtff_ids)),
                    "other_links": other_links,
                },
                "has_formula": bool(formula_hashes),
                "formula_hashes": formula_hashes,
                "raw_html_fragment": str(root),
                "source_paper_id": source_paper_id,
            }
        )

    return out
```

---

## 10.6 常见混淆点（字段语义）

1) 同一试题的重复出现  
同一 `questionId` 在多个分片或多个过滤组合中重复出现属于可观察常态（题目复用/多归类）。

2) `categoryId` 的语境差异  
在 `question/list` 链路中同时存在两类 `categoryId`：
- 请求参数中的 `categoryId`：表示“本次列表查询的分片节点”。
- 题块按钮属性中的 `categoryId`：表示“题块内部展示的分类提示”。

两者不必然相等，且语义不同。
