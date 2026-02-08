# API: `GET /zujuan-api/search?query=...`（SSE：关键词 → 检索入口 URL）

更新时间：2026-02-08

该端点返回 `text/event-stream`（Server-Sent Events, SSE）。响应为流式文本，由多段 `event:`/`data:` 行组成，用于输出“意图分析/路由生成”的结果。该端点不直接返回试题列表。

## 1) 基本信息

- 方法：`GET`
- URL：`https://zujuan.xkw.com/zujuan-api/search?query={text}`
- 认证：访客态可用（不要求登录）
- 响应：`text/event-stream; charset=utf-8`
- 连接：`keep-alive`（流式）

## 2) 请求参数

| 参数 | 位置 | 必选 | 示例 | 说明 |
|---|---|---:|---|---|
| `query` | query string | 是 | `数学` | 查询文本（需要 URL 编码） |

请求头（观测到的典型形态）：
- `Accept: text/event-stream`
- `User-Agent: Mozilla/5.0 ...`

## 3) SSE 事件结构（观测）

SSE 响应按“事件块”分段。每个事件块由若干行组成，以空行分隔。常见行形态：

```text
event: <name>
data: <payload>
```

在抽样响应中观察到的事件类型包括：
- `event: step`：进度文案（`data` 为中文提示文本）
- `event: end`：结束事件（`data` 在抽样中为 JSON 字符串）
- `event: complete`：完成提示（`data` 在抽样中可能不是严格 JSON）

抽样输出（截断，仅示意）：

```text
event: step
data: 正在分析用户意图...

event: step
data: 多维度搜题...

event: end
data: {"code":200,"type":"xuanti","policy":"知识点","url":"/czsx/zsd4680/o2","data":{"action":"知识点","params":{"bank_id":2,"knowledges":["函数"]}}}

event: complete
data: { code = 200, type = complete, url = , data = 搜索完成 }
```

### 3.1 `event: end` 的 JSON 字段（抽样）

`event: end` 的 `data` 在抽样中为 JSON，常见字段包括：
- `code`：`200`
- `type`：示例为 `xuanti`
- `policy`：命中策略（示例为“知识点”）
- `url`：站内相对 URL（可能为分类路由或检索页路由）
- `data.params`：结构化参数集合（字段集合随策略变化）

说明：`event: complete` 的 `data` 在抽样中出现了“类对象字符串”而非严格 JSON，因此其解析方式与 `event: end` 不同。

## 4) cURL 示例（读取若干秒）

```bash
curl.exe -N --max-time 5 "https://zujuan.xkw.com/zujuan-api/search?query=%E6%95%B0%E5%AD%A6"
```

若仅查看响应头：

```bash
curl.exe -I "https://zujuan.xkw.com/zujuan-api/search?query=%E6%95%B0%E5%AD%A6"
```
