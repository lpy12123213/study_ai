# 11. `question/list` 的分片维度与参数组合（访客态）

更新时间：2026-02-08

`POST /zujuan-api/question/list` 返回试题列表（HTML 片段）与总量 `total`。在章节根/知识点根等大集合下，`total` 可能达到数十万甚至更高；因此在“按条件枚举试题集合”的语义层面，常需要将一个大集合拆解为多个更小的参数组合（本文称为“分片维度”）。

本章仅描述“可用于分片的查询维度”及其与站点分类体系/参数命名的对应关系，不讨论并发、断点续爬、存储等工程实现。

相关文档：
- `docs/api/question-list.md`：接口参数与返回结构
- `docs/api/category-child-node.md`：分类树节点获取（章节/知识点/方法）
- `docs/03-entrypoints-cdn-tree.md`：CDN 预生成分类树（静态 JSON）
- `docs/16-question-list-param-validation.md`：参数语义抽样验证（哪些参数在样例中确实影响 `total`）

---

## 11.1 分片键（Shard Key）的形式化定义

对 `question/list` 而言，一个“分片”可由一组查询参数完全刻画。抽象表示为：

```text
Shard = (pageName, bankId, courseId, categoryId, provinceId, learngrade, term,
         quesAttributeId, quesType(s), quesDiff(s), paperTypeId(s), quesYear, ...)
```

说明：
- `pageName/bankId/courseId/categoryId` 通常决定了“集合的语义边界”（属于哪个分类体系/哪个节点）。
- 其余字段为筛选条件，用于将同一分类节点下的集合进一步拆分。

---

## 11.2 分类树维度（categoryId）

### 11.2.1 分类类型与 pageName 的对应关系

已观察到的常见对应关系如下（以接口与页面路由命名为准）：

| 分类语义 | `category/child_node.type` | 分类页路由前缀 | `question/list.pageName`（常见） |
|---|---:|---|---|
| 章节 | 0 | `zj{categoryId}` | `zhangjie` 或 `zj` |
| 知识点 | 1 | `zsd{categoryId}` | `zsd` |
| 解题方法 | 2 | `jtff{categoryId}` | `jtff` |

说明：同一语义可能存在多种 `pageName`（例如 `zhangjie` 与 `zj`）。具体可用取值以接口返回与页面实际行为为准。

### 11.2.2 categoryId 的来源

`categoryId` 常见信息源包括：
- 分类页 URL（例如 `.../zsd27925/` → `categoryId=27925`）
- `GET /zujuan-api/category/child_node` 的返回节点 `id`
- CDN 预生成树 JSON 的节点 `id`（见 `docs/03-entrypoints-cdn-tree.md`）

---

## 11.3 常见二级筛选维度（过滤条件）

下表列出 `question/list` 中常用于进一步拆分集合的字段。是否“实际生效”需以接口返回为准；抽样验证结论见 `docs/16-question-list-param-validation.md`。

| 维度 | 参数名（单选/多选） | 取值形态 | 说明 |
|---|---|---|---|
| 题型 | `quesType` / `quesTypes` | int / int[] | 题型枚举来自 `base` 或页面按钮属性 |
| 难度 | `quesDiff` / `quesDiffs` | int / int[] | 难度档位与含义以页面展示为准 |
| 题目属性 | `quesAttributeId` | int | 抽样中对 `total` 影响显著 |
| 年级 | `learngrade` | int | 抽样中对 `total` 有影响 |
| 学期 | `term` | int | 抽样中对 `total` 有影响 |
| 试卷类型 | `paperTypeId` / `paperTypeIds` | int / int[] | 抽样中对 `total` 有影响 |
| 地区 | `provinceId` | int | `-1` 常用于“全部”；是否生效需以接口返回为准 |
| 年份 | `quesYear` | int | 是否生效需以接口返回为准 |

---

## 11.4 多选参数的编码形式（表单序列化）

在抽样请求中，多选字段可被服务端识别的序列化形式包括：

1) 重复 key：

```text
quesTypes=2701&quesTypes=2702
paperTypeIds=2&paperTypeIds=6
quesDiffs=1&quesDiffs=2&quesDiffs=3
```

2) 带 `[]` 的 key：

```text
quesTypes[]=2701&quesTypes[]=2702
paperTypeIds[]=2&paperTypeIds[]=6
quesDiffs[]=1&quesDiffs[]=2&quesDiffs[]=3
```

抽样验证显示，上述两种写法在样例中返回的 `total` 一致；详见 `docs/16-question-list-param-validation.md`。

---

## 11.5 与 `categoryIds`/“多节点查询”相关的未解字段

在抽样中，直接在表单中追加 `categoryIds=...`（重复 key 或 `[]`）未表现出对 `total` 的影响；该参数是否需要与其它字段（例如前端脚本中出现的 `treeMultipleDic` / `canTreeMultiple` 等）组合使用，仍属于待验证项。

推进记录与待验证项见：
- `docs/15-next-exploration.md`
- `docs/16-question-list-param-validation.md`
