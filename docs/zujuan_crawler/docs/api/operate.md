# API: `/zujuan-api/operate` / `/zujuan-api/operates`（运营位/广告配置）

更新时间：2026-02-08

> 这两个端点来自页面脚本（`aop.js`）调用，用于获取“运营位/广告位/弹窗”等配置。
> **与试卷/试题抓取无关**，但它们是访客可访问的 `/zujuan-api/*` 端点，容易被误判为“业务数据接口”，因此单独记录。

## 1) 基本信息

- 方法：`GET`
- 认证：不需要登录（访客态可用）
- 返回（实测）：
  - `Content-Type: text/plain; charset=utf-8`
  - 响应体往往是 JSON（对象/数组）或 `null`（字符串）

## 2) `GET /zujuan-api/operate`

### 2.1 请求

- URL：`https://zujuan.xkw.com/zujuan-api/operate?k={key}`

| 参数 | 位置 | 必填 | 示例 | 说明 |
|---|---|---:|---|---|
| `k` | query string | 是 | `pc_home_rightbubble` | 运营位 key（场景名） |

### 2.2 返回示例

无配置时可能返回：

```text
null
```

有配置时返回一个 JSON 对象（截断）：

```json
{
  "sceneValue": "pc_home_rightbubble",
  "name": "左侧边栏",
  "acText": "https://oss-zujuan.oss-cn-hangzhou.aliyuncs.com/zujuanUpload/image/...",
  "shortLink": "http://xkw.com/....",
  "startTime": "2026-02-06T00:00:00",
  "endTime": "2026-02-28T00:00:00",
  "target": "_blank"
}
```

字段含义（按字面理解即可）：
- `sceneValue`: 场景 key（通常等于你传的 `k`）
- `acText`: 素材 URL（常见图片）
- `shortLink`: 跳转链接（可能是短链）
- `startTime` / `endTime`: 生效区间

## 3) `GET /zujuan-api/operates`

### 3.1 请求

- URL：`https://zujuan.xkw.com/zujuan-api/operates?k={k1},{k2},...`

| 参数 | 位置 | 必填 | 示例 | 说明 |
|---|---|---:|---|---|
| `k` | query string | 是 | `pc_home_rightbubble,pc_home_app_sign` | 多个 key，用逗号分隔 |

### 3.2 返回示例

返回 JSON 数组（只返回存在配置的 key；截断）：

```json
[
  {
    "sceneValue": "pc_home_rightbubble",
    "name": "左侧边栏",
    "shortLink": "http://xkw.com/...."
  }
]
```

## 4) 补充说明

- 这两个端点不返回试题/试卷列表数据。
- 响应内容可能包含外链/短链字段（如 `shortLink`），其访问与跳转语义不在本文档集范围内。
