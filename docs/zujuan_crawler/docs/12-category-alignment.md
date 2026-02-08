# 12. 分类体系对齐：章节（zj）/ 知识点（zsd）/ 解题方法（jtff）

更新时间：2026-02-08

zujuan.xkw.com 的“分类/标签”在语义上至少包含三套体系：
- 章节（章节树）
- 知识点（知识点树）
- 解题方法（方法树）

这些体系在以下位置同时出现：
- 分类页路由（例如 `.../zsd28102/`）
- 分类树接口（`GET /zujuan-api/category/child_node`）
- 试题列表接口返回片段（`question/list` 的题块链接/标签）
- CDN 预生成树（`{cdn_domain}/zujuan/tree/*.json`）

本章给出统一的对齐口径：将“页面中出现的 zsd/zj/jtff 链接”映射为 `(type, categoryId)`，并说明如何与 `question/list` 的 `pageName/categoryId` 参数对应。

相关文档：
- `docs/01-identifiers-and-urls.md`
- `docs/api/category-child-node.md`
- `docs/api/question-list.md`
- `docs/03-entrypoints-cdn-tree.md`

---

## 12.1 统一口径：`(type, categoryId)`

`GET /zujuan-api/category/child_node` 使用如下参数表达分类体系：
- `bankId`：学科题库
- `type`：分类类型（章节/知识点/方法）
- `categoryId`：父节点 ID

已观察到的 `type` 取值：

| 体系 | `type` | 路由前缀（常见） |
|---|---:|---|
| 章节 | 0 | `zj{categoryId}` |
| 知识点 | 1 | `zsd{categoryId}` |
| 解题方法 | 2 | `jtff{categoryId}` |

因此，任意分类节点均可用 `(type, categoryId)` 表达。

---

## 12.2 从题块链接抽取 `categoryId`（zsd/jtff）

### 12.2.1 知识点（zsd）链接

题块中常见知识点链接示例：

```html
<a href="/course27/zsd28102/" class="knowledge-item">函数周期性的应用</a>
```

对齐关系：
- `type = 1`
- `categoryId = 28102`

### 12.2.2 解题方法（jtff）链接

题块中常见解题方法链接示例：

```html
<a class="item" href="/course27/jtff149446">利用周期性求函数值</a>
```

对齐关系：
- `type = 2`
- `categoryId = 149446`

---

## 12.3 使用 `child_node` 观察节点存在性（样例）

`child_node` 不提供“按 id 直接查询单节点”的专用接口；常见做法是从一个已知根节点递归建立树，再在本地对节点 `id` 建索引。

示例（知识点树，`bankId=11`）：

1) 请求知识点根节点的子节点：

```bash
curl.exe "https://zujuan.xkw.com/zujuan-api/category/child_node?bankId=11&type=1&categoryId=27925&c2k=false"
```

2) 向下递归到某个父节点（示例父节点 `28087`）：

```bash
curl.exe "https://zujuan.xkw.com/zujuan-api/category/child_node?bankId=11&type=1&categoryId=28087&c2k=false"
```

响应中可观察到目标节点（示意）：

```json
{"id":28102,"name":"函数周期性的应用","parentId":28087,"type":1,"childNum":0}
```

---

## 12.4 将分类节点用于 `question/list` 查询

`question/list` 中与分类相关的关键参数为：
- `pageName`：页面类型标识（与章节/知识点/方法语义相关）
- `categoryId`：分类节点 ID

常见对应关系（观测）：

| 体系 | `pageName`（常见） | `categoryId` 来源 |
|---|---|---|
| 章节 | `zhangjie` 或 `zj` | `child_node`/CDN tree/分类页路由 |
| 知识点 | `zsd` | `child_node`/CDN tree/题块链接 |
| 解题方法 | `jtff` | `child_node`/CDN tree/题块链接 |

示例（知识点分片，`categoryId=28102`）：

```bash
curl.exe "https://zujuan.xkw.com/zujuan-api/question/list" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/gzsx/zsd28102/" ^
  --data "pageName=zsd&bankId=11&courseId=27&categoryId=28102&provinceId=-1&orderBy=2&quesType=0&quesDiff=0&quesYear=0&curPage=1"
```

说明：`Referer` 在前端请求中通常与分类页路由一致；示例使用 `href` 对应页面作为 `Referer`（详见 `docs/api/question-list.md`）。

---

## 12.5 `tre*` 链接（语义未完成映射）

在题块/分类页中可能出现类似如下路由：

```text
/course27/zsd28102/tre5-15097
```

该类路由的语义与其是否存在对应的结构化 API 尚未在本文档集中完成验证与映射。对该类链接，可在产物中保留其原始 `href/text` 作为“未映射标签”记录。

---

## 12.6 CDN 预生成树用于对齐（静态字典）

CDN 预生成树 JSON（见 `docs/03-entrypoints-cdn-tree.md`）以嵌套结构给出节点 `id/title/href/children`，可用于构造本地字典：

```text
categoryId -> {title, parentId, href, ...}
```

该字典可用于：
- 将题块链接中抽取出的 `zsdId/jtffId/zjId` 映射为节点名称、父子关系与路由信息。

说明：CDN 预生成树文件的存在性与命名不构成稳定协议；当 CDN 文件不存在或返回异常时，可使用 `child_node` 获取树结构。
