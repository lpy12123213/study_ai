# API: `GET /zujuan-api/user?t=...`（访客/用户信息）

更新时间：2026-02-08

## 1) 基本信息

- 方法：`GET`
- URL 形态：`https://zujuan.xkw.com/zujuan-api/user?t={ticks}`
- 认证：在抽样中不登录也可返回“访客态信息”，但该端点对 Cookie/Referer 等上下文更敏感
- 响应：JavaScript 变量文本（抽样 `Content-Type: text/plain; charset=utf-8`）

用途（语义层面）：
- 返回访客标记（例如 `isvisitor`）以及用户组权限字段（字段集合以实际返回为准）。

说明：该端点不属于题面/试卷列表的必要数据源；其可用性与返回结构不构成稳定承诺。

---

## 2) 请求参数

| 参数 | 位置 | 必选 | 示例 | 说明 |
|---|---|---:|---|---|
| `t` | query string | 否 | `1700000000000` | 抽样中表现为时间戳/缓存相关字段；缺省时也可能返回 |

---

## 3) 响应示例（截断）

```js
var isvisitor=true,userinfo={},usergroup={"GroupID":1,"GroupName":"普通用户",...},usermoney={},...
```

解析说明：
- 该响应为 JS 代码片段，不是 JSON。
- 若仅需判断访客态，可用正则匹配 `isvisitor=true` / `isvisitor=false`。

---

## 4) 非目标响应（观测）

在缺少上下文（Cookie/Referer）时，该端点在抽样中可能出现：
- `404`
- `text/html` 的挑战页（包含 `aliyun_waf_*`、`acw_sc__v2` 等特征）

挑战页/登录页判别特征见：`docs/02-session-cookies-headers.md` 与 `docs/troubleshooting.md`。
