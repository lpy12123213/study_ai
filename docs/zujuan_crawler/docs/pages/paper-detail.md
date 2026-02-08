# 页面：`/{bankId}p{paperId}.html`（试卷详情页）

更新时间：2026-02-08

示例：
- `https://zujuan.xkw.com/11p3044139.html`

试卷详情页通常包含：
- 多个题块（可抽取 `questionId` 列表）
- 试卷元信息（可能以内嵌 JS 变量形式提供）
- 题型结构与题目顺序（可能以内嵌 `paperJson` 提供）

可用性说明：
- 在部分访问模式下，该页面可能返回挑战页 HTML（不包含业务内容）。挑战页判别特征见 `docs/02-session-cookies-headers.md` 与 `docs/13-stability-profile.md`。

---

## 1) URL 可直接解析的字段

- `bankId`：URL 前缀数字（`11p...` 中的 `11`）
- `paperId`：`p` 后的数字（`...p3044139.html` 中的 `3044139`）

---

## 2) HTML 结构（观测）：题块与 `questionId` 抽取

试卷页通常包含多个题块根节点，形态与列表题块相似：

```html
<div class="tk-quest-item quesroot"
     questionindex="0"
     questionid="31298690"
     bankid="11">
  ...
</div>
```

可抽取的属性字段：
- `questionid` → `questionId`
- `questionindex` → 卷内顺序（页面级序号）
- `bankid` → `bankId`

简单正则（仅用于抽取 `questionId` 的一种形式）：

```regex
questionid="(\d+)"
```

---

## 3) 内嵌 JS 变量（观测）：`var paper = {...}`

在抽样页面中，HTML 中常内嵌一个对象变量（变量名常见为 `paper`），包含试卷元信息（示意截断）：

```js
var paper = {
  "id": 3044139,
  "title": "...",
  "bankId": 11,
  "area": {"id": 1, "name": "全国"},
  "grade": {"id": 12, "name": "高三"},
  "paperType": {"id": 6, "name": "专题练习", "parentId": 0},
  "year": 2027,
  "time": "2026-02-07T23:07:37",
  "quesCount": 12
};
```

字段集合与命名以页面实际返回为准。

抽取方式（可复现口径）：
1) 在 HTML 文本中定位 `var paper =` 的起始位置。
2) 从第一个 `{` 起做花括号配对，截取对象文本。
3) 解析为 JSON（若存在尾逗号、`true/false` 等非严格 JSON 细节，则需要做兼容处理；该兼容处理属于实现方逻辑，不属于站点协议）。

---

## 4) 内嵌 JS 变量（观测）：`var paperJson = {...}`

在抽样页面中，页面也可能内嵌 `paperJson`，包含题型分组与题目列表（示意截断）：

```js
var paperJson = {
  "paperTitle": "...",
  "paperDiff": "...",
  "quesTypes": [
    {
      "id": 2701,
      "name": "单选题",
      "quesList": [
        {"quesCode":"1","id":31298690,"quesDiff":0.94}
      ]
    }
  ]
};
```

若可稳定抽取并解析 `paperJson`，则可直接获得：
- 题型分组（`quesTypes[].id/name`）
- 卷内题号（`quesCode`）与题目 ID（`id`）

抽取方式与 `paper` 类似：定位变量名后做花括号配对截取，再进行解析。

---

## 5) 权限提示变量（观测）：`authAlertInfo`

页面脚本中可能出现权限提示对象，例如：

```js
var authAlertInfo = JSON.parse('{\"canVisit\":true}')
```

当 `canVisit=false` 或页面出现登录/权限不足提示时，页面内容不包含可用题面数据；本文档范围不包含绕过逻辑。

---

## 6) 题目详情页链接（观测）

试卷页通常也包含题目详情链接：

```text
/{bankId}q{questionId}.html
```

该链接的访客态可用性同样可能受到挑战页影响，详见 `docs/pages/question-detail.md`。
