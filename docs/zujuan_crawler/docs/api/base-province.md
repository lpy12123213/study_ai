# API: `/zujuan-api/base-province`（省市区/地区枚举）

## 1) 基本信息

- 方法：`GET`
- URL：`https://zujuan.xkw.com/zujuan-api/base-province`
- 认证：不需要登录（访客态可用）
- Content-Type（实测）：`text/plain; charset=utf-8`
- 返回体类型：**JavaScript 变量**（不是纯 JSON）

用途：
- 构建地区筛选（常用字段：`provinceId` / `areaId`）
- 一些页面会根据 IP 写入 `ip2ProvinceId` Cookie（可作为默认地区），但爬虫不必依赖

## 2) 请求参数

无。

## 3) 返回示例（截断）

```js
var province_list=[
  {"id":1,"name":"全国","fullName":"全国","parentId":0,"Classify":0,"OrderIndex":0,"examAreaId":0},
  {"id":110000,"name":"北京","fullName":"北京市","parentId":0,"Classify":1,"OrderIndex":2,"examAreaId":0},
  ...
]
```

字段含义（常见）：
- `id`：地区 ID（省/市/区）
- `name` / `fullName`：名称
- `parentId`：父节点（用于构建树）
- `Classify` / `OrderIndex`：分类/排序（具体以站点逻辑为准）
- `examAreaId`：考试区域 ID（如果存在）

## 4) 解析方法

与 `/zujuan-api/base` 类似，先把 JS 变量里的数组截出来再 `json.loads`。

```python
import json, re

def parse_base_province(text: str):
    m = re.search(r"var\\s+province_list\\s*=\\s*(\\[.*\\])\\s*$", text, re.S)
    if not m:
        raise ValueError("unexpected /zujuan-api/base-province format")
    return json.loads(m.group(1))
```

