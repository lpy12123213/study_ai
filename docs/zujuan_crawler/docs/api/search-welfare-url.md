# API: `/zujuan-api/search/welfare-url`（福利关键词 → 跳转 URL 文本）

更新时间：2026-02-08

> 这是一个“小功能”接口：用于在站内搜索框输入特定前缀（如 `#福利#...`）时，返回一个可跳转的 URL。
> 对“无登录爬虫主流程”没有帮助，但它是 **访客可用** 的 `/zujuan-api/*` 端点之一，容易被误以为是“搜题接口”，因此单独记录。

## 1) 基本信息

- 方法：`GET`
- URL：`https://zujuan.xkw.com/zujuan-api/search/welfare-url`
- 认证：不需要登录（访客态可用）
- 返回：`text/plain; charset=utf-8`
  - 可能是一个 URL 字符串（非 JSON）
  - 也可能是空响应体（`Content-Length: 0`）

## 2) Query 参数

| 参数 | 类型 | 必填 | 示例 | 说明 |
|---|---|---:|---|---|
| `keyword` | string | 是 | `#福利#数学` | 关键词文本（需要 URL 编码） |

说明（来自前端逻辑观测）：
- 只有当 `keyword` 以 `#福利#` 开头时，站点前端才会触发该接口调用
- 该接口不返回“试题列表”，只是一个“跳转 URL”字符串

## 3) 返回示例（实测）

实测请求：

```bash
curl.exe -i "https://zujuan.xkw.com/zujuan-api/search/welfare-url?keyword=%23%E7%A6%8F%E5%88%A9%23%E6%95%B0%E5%AD%A6"
```

实测响应（截断）：

```text
HTTP/1.1 200 OK
Content-Type: text/plain; charset=utf-8
Content-Length: 0
```

含义：
- 200 但 `Content-Length: 0`：表示没有匹配到可跳转的福利 URL（或该福利活动已下线）

## 4) 补充说明

该端点不返回试题列表或试卷列表，仅返回“福利关键词 → 跳转 URL”的文本结果。

与“试题/试卷列表”相关的端点见：
- `POST /zujuan-api/question/list`
- `POST /zujuan-api/paper/list`
- `GET /zujuan-api/search?query=...`（SSE：返回检索入口 URL，不直接返回题目）
