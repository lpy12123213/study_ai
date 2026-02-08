# 15. 待验证项清单（后续探索方向）

更新时间：2026-02-08

本章以“待验证问题（To Verify）”形式列出本文档集尚未覆盖或尚未完全确认的点。每一项均以：
- 问题描述（需要被证实/证伪的命题）
- 可能的验证输入（抓包/抽样请求的参数组合）
- 预期输出（可观察判定）

的方式表述，便于后续按项推进。

范围边界：
- 仅讨论公开可访问内容的研究与验证。
- 对于需要登录/会员/付费/验证码/挑战页才能访问的内容，本文档不纳入验证范围。

---

## 15.1 `question/list`：未完全确认的参数语义

背景：`POST /zujuan-api/question/list` 为访客态的核心入口。参数语义若存在误判，可能导致“集合漏抓/重复抓/过滤不生效”。

待验证问题：
1) `pageName` 的校验严格性是否随时间变化（是否存在强校验、弱校验或仅用于统计的情形）。
2) 多节点/多选类字段在何种条件下生效（例如 `categoryIds` 是否需要与其它参数组合）。
3) `data.total` 的统计口径是否稳定（是否与实际分页可抽取到的题块数一致）。

现有材料：
- 参数抽样验证：`docs/16-question-list-param-validation.md`
- 探测脚本：`docs/examples/question-list-param-probe.py`
- 接口参数表：`docs/api/question-list.md`

---

## 15.2 分类树来源：CDN tree 与 `child_node` 的一致性边界

背景：分类树存在两类来源：
- 动态接口：`GET /zujuan-api/category/child_node`
- 静态 JSON：`GET {cdn_domain}/zujuan/tree/*.json`

待验证问题：
1) 不同 `bankId` 下，CDN tree 文件的存在性覆盖面（尤其是 `j_{bankId}.json`）。
2) CDN tree 与 `child_node` 在不同层级的结构一致性（不仅限于 root 层 `children` 数量）。
3) CDN tree 节点 `id` 作为 `question/list.categoryId` 的可用性边界（是否存在节点可见但无法抓到题的情况）。

现有材料：
- CDN tree 规则与样例：`docs/03-entrypoints-cdn-tree.md`
- `child_node` 接口：`docs/api/category-child-node.md`

---

## 15.3 公式链路：`.mml` 可用性与转换覆盖率的长期回归

背景：公式 LaTeX 获取依赖以下链路：题块中公式图片 `{hash}` → `{hash}.mml`（Base64/MathML）→ LaTeX 转换。

待验证问题：
1) `.mml` 的可用性是否在不同学科/不同题源中一致（404 率）。
2) Base64 解码后是否稳定包含 `<math>`（格式稳定性）。
3) MathML → LaTeX 转换对不同公式结构的覆盖边界（失败样本类型归类）。

现有材料：
- 公式规则与转换示例：`docs/08-formula-mml-latex.md`
- 覆盖率探测脚本：`docs/examples/formula-coverage-probe.py`

---

## 15.4 `paper/list`：列表片段元信息的字段抽取覆盖面

背景：`POST /zujuan-api/paper/list` 返回 `data.html` 片段。除 `paperId` 外，片段还包含标题、地区、年级等文本信息，但其字段化规则未在所有样式下验证。

待验证问题：
1) 不同 `paperTypeId`、不同学科库下的卷块 DOM 差异是否影响字段抽取。
2) 文本字段的标准化口径（地区/学校/年份等）与接口参数（例如 `provinceId/schoolId`）之间的对齐关系。

现有材料：
- `paper/list` 接口：`docs/api/paper-list.md`
- 卷块片段结构：`docs/pages/list-html-fragments.md`

---

## 15.5 静态资源：图片域名/路径形态的覆盖面

背景：题面图片并非仅来自 `staticzujuan.xkw.com`；不同题源可能引入其它域名与路径形态。

待验证问题：
1) 不同学科/题型下的图片 host 与路径前缀分布统计。
2) 对非 `staticzujuan.xkw.com` 域名资源的可访问性与稳定性（是否存在重定向/403/挑战页替换）。

现有材料：
- 静态资源规则：`docs/07-static-assets.md`

---

## 15.6 SSE 搜索入口：事件结构与 URL 反推

背景：`GET /zujuan-api/search?query=` 返回 SSE（`text/event-stream`），其中结束事件可能携带站内检索入口 URL。

待验证问题：
1) SSE 事件的结构是否稳定（`event:end`/`event:complete` 等事件的字段形态）。
2) 结束事件中返回的 URL 是否可系统性反推出 `bankId/courseId/categoryId` 或其它筛选参数。

现有材料：
- SSE 接口说明：`docs/api/search-sse.md`

---

## 15.7 内容一致性与重复（跨入口复用）

背景：同一试题会出现在多个入口与多个分类节点中；这是题库复用与多归类的自然结果。

待验证问题：
1) 不同入口（paper → question 与 category → question）获得的题块 HTML 是否存在系统性差异。
2) 同一 `questionId` 在不同时间抓取时 HTML 是否存在版本变化（题干修订/排版变动）。

现有材料：
- 概念模型：`docs/06-storage-model.md`
- 产物契约：`docs/09-output-contract.md`
