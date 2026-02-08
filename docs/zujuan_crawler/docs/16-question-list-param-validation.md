# 16. `question/list` 参数语义验证（抽样探测结果）

更新时间：2026-02-08

本章记录对 `POST /zujuan-api/question/list` 的抽样探测结果，关注点为：
- `pageName` / `Referer` 是否被服务端严格校验（在样例范围内）
- 哪些筛选参数在样例中确实影响 `data.total`
- 多选数组参数的表单序列化方式是否被服务端识别
- `data.total` 在小集合场景下是否可闭环核对

范围与限制：
- 所有结论均为 2026-02-08 的单机抽样观测结果。
- 站点参数校验、风控策略与返回结构可能随时变化；本章不提供稳定性承诺。

相关文档：
- 接口参数表：`docs/api/question-list.md`
- 探测脚本：`docs/examples/question-list-param-probe.py`

---

## 16.1 探测脚本与样例配置

脚本：`docs/examples/question-list-param-probe.py`

脚本内置的样例参数（可替换为其它学科/节点）：
- `bankId=11`（高中数学）
- `courseId=27`
- 章节根（zj）：`categoryId=135303`（路由示例：`/gzsx/zj135303/`）
- 知识点叶子（zsd）：`categoryId=28102`（路由示例：`/gzsx/zsd28102/`）

脚本输出为 TSV 表（每行一个参数变体），包含：HTTP 状态、`code`、`total`、从第一页抽取到的 `questionId` 数量等字段。

---

## 16.2 结论 1：`pageName` / `Referer` 在该样例下未表现为强校验

对同一组参数（章节根 `categoryId=135303`）进行对照：
- `pageName=zhangjie`（常见取值）
- `pageName=zj`（常见别名）
- `pageName=not_a_page`（明显不符合页面命名）
- `Referer` 为章节路由 / 知识点路由 / 缺失

实测节选（以脚本输出为准）：

```text
label        status  code  total    qids  note
zj_ok        200     0     360939   10    pageName=zhangjie + zj referer
zj_alias     200     0     360939   10    pageName=zj + zj referer
page_wrong   200     0     360939   10    pageName=not_a_page + zj referer
ref_mismatch 200     0     360939   10    pageName=zhangjie + zsd referer
no_referer   200     0     360939   10    no referer
```

可观察结论：在该样例与该时点，`pageName` 与 `Referer` 的差异未导致 `code!=0` 或 `total` 变化。

---

## 16.3 结论 2：以下参数在样例中确实影响 `data.total`

本节以知识点分片（`pageName=zsd&categoryId=28102`）为对照基线，比较不同参数对 `data.total` 的影响。

### 16.3.1 `quesAttributeId`

实测节选：

```text
zsd_leaf_base total=4321
attr_1        total=346
attr_2        total=3604
attr_3        total=342
attr_4        total=24
attr_5        total=4
```

可观察结论：`quesAttributeId` 在该样例下显著改变集合规模。

取值集合来源：`GET /zujuan-api/base` 的 `QuesAttributeList`（不同 `bankId` 可能不同），详见 `docs/api/base.md`。

### 16.3.2 `learngrade`

实测节选：

```text
grade_10 total=1702
grade_11 total=1098
grade_12 total=3181
```

可观察结论：`learngrade` 在该样例下改变集合规模。

### 16.3.3 `term`

实测节选：

```text
term_1 total=2918
term_2 total=1967
```

可观察结论：`term` 在该样例下改变集合规模。

### 16.3.4 `paperTypeId` / `paperTypeIds`

实测节选：

```text
paperTypeId_6 total=1904
paperTypeId_2 total=109
paperTypeId_9 total=1247
```

可观察结论：`paperTypeId` 在该样例下显著改变集合规模。

### 16.3.5 `quesDiff` / `quesDiffs`

实测节选：

```text
diff_single_2 total=734
diffs_repeat  total=819
```

可观察结论：难度字段在该样例下改变集合规模。

---

## 16.4 结论 3：多选数组参数的两种序列化方式在样例中均可识别

以题型多选（2701 + 2702）为例，对比两种表单编码：

1) 重复 key：

```text
quesTypes=2701&quesTypes=2702
```

2) `[]` key：

```text
quesTypes[]=2701&quesTypes[]=2702
```

实测结果：两种写法在该样例下返回的 `total` 一致：

```text
types_repeat  total=3011
types_bracket total=3011
```

脚本同时验证了 `paperTypeIds` 与 `quesDiffs` 的两种序列化写法在样例中等价（以 `total` 作为可观察判据）。

---

## 16.5 结论 4：`categoryIds` 的朴素传参在样例中未表现为生效

脚本在基线参数上追加 `categoryIds=...`（重复 key 或 `[]` key）后，`total` 未发生变化。

可观察结论：在该样例与该时点，`categoryIds` 字段未表现为影响集合规模。

备注：该字段是否需要与其它前端字段组合使用（例如脚本中出现的 `treeMultipleDic` / `canTreeMultiple`），属于待验证项，见 `docs/15-next-exploration.md`。

---

## 16.6 结论 5：`data.total` 在小集合样例中可闭环核对

对 `total` 很小的分片，脚本通过“翻页抓完并计数”的方式做闭环核对：

- `quesAttributeId=5`：`total=4`，实际抓取到 unique `questionId = 4`
- `quesAttributeId=4`：`total=24`，实际抓取到 unique `questionId = 24`

可观察结论：在该样例与该时点，`data.total` 与实际可分页抽取到的 `questionId` 数量一致。
