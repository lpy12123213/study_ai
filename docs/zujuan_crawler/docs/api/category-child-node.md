# API: `GET /zujuan-api/category/child_node`（分类树子节点）

更新时间：2026-02-08

## 1) 基本信息

- 方法：`GET`
- URL：`https://zujuan.xkw.com/zujuan-api/category/child_node`
- 认证：访客态可用（不要求登录）
- 响应：JSON（抽样响应 `Content-Type` 可能为 `application/json; charset=utf-8` 或 `application/json`）

用途（语义层面）：
- 按 `(bankId, type, categoryId)` 获取某个分类节点的“直接子节点列表”（一层）。
- 分类体系包括：章节（type=0）、知识点（type=1）、解题方法（type=2）。

相关文档：
- 分类体系对齐：`docs/12-category-alignment.md`
- CDN 预生成树：`docs/03-entrypoints-cdn-tree.md`

---

## 2) Query 参数

| 参数 | 类型 | 必选 | 示例 | 说明 |
|---|---|---:|---|---|
| `bankId` | int | 是 | `11` | 学科题库 ID |
| `type` | int | 是 | `0` / `1` / `2` | 分类类型：0=章节，1=知识点，2=解题方法 |
| `categoryId` | int | 是 | `135303` | 父节点 ID（返回该节点的直接子节点） |
| `c2k` | bool/string | 否 | `false` | 站点内部参数；抽样请求常见为 `false` |

说明：
- `categoryId=0` 不等价于“根”。在部分 `type` 下，`categoryId=0` 可能返回错误对象（见第 4 节）。

---

## 3) 请求头（观测到的典型形态）

抽样可用请求中，常见请求头包括：
- `X-Requested-With: XMLHttpRequest`
- `Referer: https://zujuan.xkw.com/{courseIdPy}/zj{categoryId}/`（或对应 `zsd/jtff` 路由）
- `User-Agent: Mozilla/5.0 ...`

---

## 4) 响应格式

### 4.1 成功响应：JSON 数组

成功时返回 JSON 数组，每个元素为一个“子节点”对象。

章节（`type=0`）示例（截断）：：

```json
[
  {"id":135305,"name":"第一章 ...","parentId":135303,"type":0,"qbmId":185429,"childNum":6,"dataSource":0},
  {"id":135307,"name":"第二章 ...","parentId":135303,"type":0,"qbmId":185437,"childNum":4,"dataSource":0}
]
```

知识点（`type=1`）示例（截断）：

```json
[
  {"id":27926,"name":"集合与常用逻辑用语","parentId":27925,"type":1,"qbmId":10417,"childNum":2,"dataSource":0},
  {"id":27927,"name":"函数与导数","parentId":27925,"type":1,"qbmId":10540,"childNum":7,"dataSource":0}
]
```

常见字段（观测）：
- `id`：节点 ID（子节点的 `categoryId`）
- `name`：节点名称
- `parentId`：父节点 ID（等于请求参数 `categoryId`）
- `type`：分类类型（与请求参数一致）
- `childNum`：子节点数量；`0` 常表示叶子节点
- `qbmId` / `dataSource`：站点内部字段（是否使用由实现方决定）

### 4.2 异常响应：JSON 对象（非数组）

当参数不合法或服务端异常时，可能返回对象而非数组，例如：

```json
{
  "code": 500,
  "message": "系统异常，请稍后重试。",
  "type": "InvalidOperationException",
  "errorId": "..."
}
```

---

## 5) `categoryId`（根节点）的信息源

该接口需要一个可用的父节点 `categoryId` 作为起点。常见信息源包括：

1) 分类页路由中的数字部分（示例）：
- 章节：`https://zujuan.xkw.com/gzsx/zj135303/` → `categoryId=135303`
- 知识点：`https://zujuan.xkw.com/gzsx/zsd27925/` → `categoryId=27925`

2) CDN 预生成树节点 `id`：
- `GET {cdn_domain}/zujuan/tree/lk_{bankId}.json`（知识点）
- `GET {cdn_domain}/zujuan/tree/ct_{bankId}_{textbookVersionId}.json`（章节）

3) `GET /zujuan-api/base` 的枚举结构中出现的分类根节点（不同 bankId 结构不同），详见：
- `docs/api/base.md`

---

## 6) 与“整棵树”获取的关系

`child_node` 单次请求只返回“一层子节点”。若需要得到整棵树结构，需要对返回节点继续以 `id` 作为下一次 `categoryId` 发起请求，直至叶子节点（`childNum=0`）。

CDN 预生成树提供了“整棵树”的静态 JSON（存在性与命名不保证），见：
- `docs/03-entrypoints-cdn-tree.md`
