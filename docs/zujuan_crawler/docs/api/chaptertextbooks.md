# API: `/zujuan-api/chaptertextbooks`（教材章节导航 HTML）

## 1) 基本信息

- 方法：`GET`
- URL：`https://zujuan.xkw.com/zujuan-api/chaptertextbooks`
- 认证：不需要登录（访客态可用）
- 返回：HTML 片段（实测 `text/html; charset=utf-8`）

用途：
- 快速获取“某教材版本（textbookVersionId）下的一级章节列表”
- 常用于辅助拿到章节节点 ID（`chapter-id`），再用 `category/child_node` 做递归

## 2) Query 参数

| 参数 | 类型 | 必填 | 示例 | 说明 |
|---|---|---:|---|---|
| `textbookVersionId` | int | 是 | `135303` | 教材/章节根 ID（常与 `.../zj135303/` 一致） |
| `url` | string | 是 | `/gzsx/zj135303/` | 当前页面路径（用于服务端判断上下文） |

请求头（观测到的典型形态）：
- `X-Requested-With: XMLHttpRequest`
- `Referer: https://zujuan.xkw.com/gzsx/zj135303/`

## 3) 返回示例（截断）

```html
<span class="menu-item__title">教材：</span>
<div class="menu-item__navs">
  <a class="item font-item" href="/gzsx/zj135303/" chapter-id="135305" data-qbmid="185429">...</a>
  <a class="item font-item" href="/gzsx/zj135303/" chapter-id="135307" data-qbmid="185437">...</a>
  ...
</div>
```

解析要点：
- `chapter-id="135305"`：就是后续 `categoryId`（章节节点）
- `data-qbmid`：站点内部字段，可选保存

## 4) 补充说明

- 该接口返回 HTML 片段（不是 JSON）。
- 片段中 `chapter-id` 可作为章节节点 ID 使用；章节树的结构化获取仍以 `category/child_node` 或 CDN tree 为准（见 `docs/api/category-child-node.md`、`docs/03-entrypoints-cdn-tree.md`）。
