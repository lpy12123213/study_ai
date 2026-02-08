# cURL 示例（访客态；允许访客 Cookie）

更新时间：2026-02-08

本文件给出若干可复现的 `curl.exe` 请求示例，用于访问本文档集覆盖的访客态端点。

说明：
- 示例不包含登录态 Cookie。
- 站点对请求上下文（Cookie/Referer/User-Agent）可能敏感；示例尽量模拟前端常见请求头形态。

---

## 0) 使用 cookie jar（访客 Cookie 持久化）

在浏览器链路中，站点会下发访客 Cookie。使用 `curl` 进行多次请求时，可使用 cookie jar 文件保存并回传这些 Cookie。

示例：先请求一个轻量端点保存 Cookie：

```bash
curl.exe -s -c cookies.txt "https://zujuan.xkw.com/zujuan-api/base" > NUL
```

后续请求中携带并更新 cookie jar：

```bash
curl.exe -b cookies.txt -c cookies.txt "https://zujuan.xkw.com/zujuan-api/base-province"
```

---

## 1) 获取学科/题型等枚举：`GET /zujuan-api/base`

```bash
curl.exe -b cookies.txt -c cookies.txt ^
  -H "User-Agent: Mozilla/5.0" ^
  "https://zujuan.xkw.com/zujuan-api/base"
```

---

## 2) 获取省市区枚举：`GET /zujuan-api/base-province`

```bash
curl.exe -b cookies.txt -c cookies.txt ^
  -H "User-Agent: Mozilla/5.0" ^
  "https://zujuan.xkw.com/zujuan-api/base-province"
```

---

## 3) 试卷列表：`POST /zujuan-api/paper/list`

```bash
curl.exe -b cookies.txt -c cookies.txt "https://zujuan.xkw.com/zujuan-api/paper/list" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/shijuan/" ^
  --data "pageName=shijuan&bankId=11&learnGradeId=0&paperTypeId=0&schoolId=0&provinceId=-1&paperYear=0&paperLevelId=0&newCategoryId=0&isFreshPaper=0&orderBy=0&curPage=1"
```

---

## 4) 试题列表：`POST /zujuan-api/question/list`

```bash
curl.exe -b cookies.txt -c cookies.txt "https://zujuan.xkw.com/zujuan-api/question/list" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/gzsx/zj135303/" ^
  --data "pageName=zhangjie&bankId=11&courseId=27&categoryId=135303&provinceId=-1&orderBy=2&quesType=0&quesDiff=0&quesYear=0&curPage=1"
```

---

## 5) 分类树子节点：`GET /zujuan-api/category/child_node`

```bash
curl.exe -b cookies.txt -c cookies.txt ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/gzsx/zj135303/" ^
  "https://zujuan.xkw.com/zujuan-api/category/child_node?bankId=11&type=0&categoryId=135303&c2k=false"
```

---

## 6) 学校搜索：`GET /zujuan-api/schools`

```bash
curl.exe -b cookies.txt -c cookies.txt ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/shijuan/" ^
  "https://zujuan.xkw.com/zujuan-api/schools?1=1&keyword=%E5%8C%97%E4%BA%AC"
```

---

## 7) SSE 搜索：`GET /zujuan-api/search?query=...`

```bash
curl.exe -N --max-time 5 "https://zujuan.xkw.com/zujuan-api/search?query=%E6%95%B0%E5%AD%A6"
```

---

## 8) 判别“非目标响应”（登录页/挑战页）

示例：请求一个在访客态常见返回 403/302 的端点（用于观察响应形态）：

```bash
curl.exe -i "https://zujuan.xkw.com/zujuan-api/qrcode" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  --data "url=https://zujuan.xkw.com/11p3044139.html"
```

判别要点（可观察特征）：
- `302` 且 `Location: .../login?ReturnUrl=...`：重定向到登录页
- `Content-Type: text/html` 且包含 `login.css`：登录页 HTML
- `Content-Type: text/html` 且包含 `<body onload=\"check()\">` 或 `aliyun_waf_aa`/`acw_sc__v2`：挑战页 HTML
