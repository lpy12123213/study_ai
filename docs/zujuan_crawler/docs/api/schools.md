# API: `/zujuan-api/schools`（学校搜索）

## 1) 基本信息

- 方法：`GET`
- URL 形态：`https://zujuan.xkw.com/zujuan-api/schools?1=1&keyword=...`
- 认证：不需要登录（访客态可用）
- 返回：JSON（实测 Content-Type 可能是 `text/plain; charset=utf-8`）

用途：
- 在 paper 列表中过滤 `schoolId` 时，需要先通过该接口把学校名称映射到 `id`

## 2) Query 参数

| 参数 | 类型 | 必填 | 示例 | 说明 |
|---|---|---:|---|---|
| `1` | int | 否 | `1` | 站点前端固定携带的无意义参数（保留即可） |
| `keyword` | string | 是 | `北京` | 搜索关键词（需要 URL 编码） |
| `areaId` | int | 否 | `110000` | 地区过滤（可选；从 URL/省份表推导） |

请求头（观测到的典型形态）：
- `X-Requested-With: XMLHttpRequest`
- `Referer: https://zujuan.xkw.com/shijuan/`

## 3) 返回示例（截断）

```json
{
  "code": 200,
  "data": [
    {"id": 441856, "name": "北京京北幼儿园"},
    {"id": 83272, "name": "北京京西学校"}
  ]
}
```

## 4) 注意事项

- 返回 `code=200` 才表示成功（与其他接口 `code="0"` 的风格不同）
