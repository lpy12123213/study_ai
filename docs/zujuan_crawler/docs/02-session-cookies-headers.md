# 2. 会话、Cookie 与请求头（访客态）

本章说明“访客态请求链路”的可观察约束：同一 URL 在不同的 Cookie / Referer / User-Agent 等条件下，响应类型可能发生变化（例如从 JSON 变为 HTML 挑战页）。文档后续章节中的示例请求均以“浏览器正常访问链路可复现”的请求头与 Cookie 形态为基线。

## 2.1 访客态响应的可观察依赖

在本机对 zujuan.xkw.com 的抽样请求中，可复现如下现象：

- 同一 URL 在不同访问条件下可能返回不同 `Content-Type`：
  - 目标响应：`application/json`（列表接口）或正常业务 HTML（详情页）
  - 非目标响应：`text/html` 的挑战页 / 登录页（内容不等同于目标数据）
- 部分接口在缺少某些上下文（Cookie/Referer）时可能返回 `404` 或返回业务无关的占位内容。

因此，任何“数据获取成功/失败”的判定均不应仅依据 HTTP 状态码，而应以 `Content-Type` 与响应体特征作为判定条件（见 2.4）。

## 2.2 常见 Cookie（访客态）

Cookie 名称与生效逻辑可能随站点调整而变化。下表仅描述在访客态抓包/请求中常见的 Cookie 名称及其可观察用途（不构成稳定协议承诺）。

| Cookie 名 | 可观察用途/特征 | 备注 |
|---|---|---|
| `acw_tc` / `aliyungf_tc` | 网关/风控链路相关 | 可能存在有效期；过期后响应类型可能变化 |
| `acw_sc__v2` | 风控挑战计算出的 Cookie | 站点在挑战页中可能通过脚本写入后刷新 |
| `__RequestVerificationToken` | 请求校验相关字段（在部分链路中出现） | 是否必需取决于具体端点与站点策略 |
| `zj-device-id` | 设备标识（在部分链路中出现） | 是否必需取决于具体端点与站点策略 |
| `bankId` | 当前学科库 ID（常见为浏览器访问学科页面后写入） | 该值也作为多数接口参数出现 |
| `chapter_{bankId}` | 当前教材/章节根节点相关（在访问章节页后可能写入） | 常见于章节相关页面链路 |

合规边界：
- Cookie 仅使用你本人通过浏览器正常访问站点时获得的访客 Cookie。
- 本文档不讨论登录态 Cookie 的使用，也不提供任何绕过访问控制的方法。

## 2.3 请求头（Headers）

### 2.3.1 列表接口（`/zujuan-api/*`）的典型请求头形态

在抽样可用请求中，`/zujuan-api/*` 端点常见请求头包括：

| Header | 示例值（仅示意） | 说明 |
|---|---|---|
| `User-Agent` | 浏览器 UA 字符串 | 缺失或异常 UA 可能导致返回占位内容或 HTML |
| `Accept` | `application/json, text/javascript, */*; q=0.01` | 用于表达期望的响应类型 |
| `Referer` | `https://zujuan.xkw.com/shijuan/` | 作为页面上下文来源（站点可能校验） |
| `X-Requested-With` | `XMLHttpRequest` | 常见于前端 AJAX 请求 |
| `Content-Type` | `application/x-www-form-urlencoded; charset=UTF-8` | 仅适用于 POST 表单 |

文档中的 cURL/Python 示例会在“请求示例”段落中给出具体可复现的 header 组合。

### 2.3.2 HTML 详情页的典型请求头形态

对于 `/{bankId}p{paperId}.html`、`/{bankId}q{questionId}.html` 等 HTML 页面，抽样可用请求的请求头通常更接近浏览器导航请求（`Accept: text/html,...`）。

## 2.4 非目标响应的识别（登录页 / 挑战页）

很多情况下 HTTP `200 OK` 并不意味着获得了目标数据。本节给出两类常见“非目标响应”的判别要点。

### 2.4.1 登录页（可观察特征）

- `Content-Type: text/html`
- HTML 中包含登录相关资源或文案（例如 `/css/login.css`、`login-popup.css`、“登录”提示等）

判定：该内容通常表示目标数据需要登录或权限。本文档范围不包含绕过登录/权限控制的逻辑。

### 2.4.2 挑战页（可观察特征）

挑战页的 HTML 特征在不同时间段可能不同，常见特征包括但不限于：

- HTML 顶部包含 `<body onload="check()">`
- 页面中出现 `alicfw_gfver` 等风控相关标识字符串
- `<head>` 中出现 `<meta name="aliyun_waf_aa" ...>` / `<meta name="aliyun_waf_bb" ...>`
- 页面脚本尝试写入 `acw_sc__v2` 等 Cookie 后触发 `reload()`

判定：该响应不包含目标页面内容。本文档不提供挑战页的绕过/对抗实现。
