# API: `POST /zujuan-api/question/list`（试题列表分页）

更新时间：2026-02-08

## 1) 基本信息

- 方法：`POST`
- URL：`https://zujuan.xkw.com/zujuan-api/question/list`
- 认证：访客态可用（不要求登录）
- 请求体：`application/x-www-form-urlencoded; charset=UTF-8`
- 响应：JSON（抽样响应 `Content-Type` 常为 `application/json; charset=utf-8`）

用途（语义层面）：
- 按章节/知识点/解题方法节点（`categoryId`）与其它过滤条件，分页获取试题列表。
- 返回体中的 `data.html` 为 HTML 片段，包含多个题块；题块内包含 `questionId`、题干/选项片段、题源链接、知识点/方法链接、以及题型/难度等元信息（以片段为准）。

相关文档：
- 题块解析：`docs/10-question-fragment-to-json.md`
- 片段结构：`docs/pages/list-html-fragments.md`
- 参数抽样验证：`docs/16-question-list-param-validation.md`

---

## 2) 请求头（观测到的典型形态）

抽样可用请求中，常见请求头包括：

| Header | 示例值（仅示意） | 说明 |
|---|---|---|
| `Content-Type` | `application/x-www-form-urlencoded; charset=UTF-8` | POST 表单编码 |
| `X-Requested-With` | `XMLHttpRequest` | 前端 AJAX 常见标识 |
| `Referer` | `https://zujuan.xkw.com/gzsx/zsd28102/` | 前端请求通常携带页面路由作为来源 |
| `User-Agent` | `Mozilla/5.0 ...` | 抽样中 UA 形态会影响部分端点的响应类型 |

说明：`Referer` 与 `pageName` 的严格校验程度在样例中未表现为强校验（见 `docs/16-question-list-param-validation.md`），但该行为不构成稳定承诺。

---

## 3) 表单参数

### 3.1 参数表（常见字段）

下表覆盖在抽样抓包/前端脚本中出现的常用字段。未列出的字段可能存在于前端脚本对象中，但未在本文中逐一确认语义。

| 参数 | 类型 | 常见取值 | 是否必需（按分类查询语境） | 说明 |
|---|---|---|---:|---|
| `pageName` | string | `zhangjie` / `zj` / `zsd` / `jtff` | 是 | 页面语义标识（章节/知识点/方法） |
| `bankId` | int/string | `11` | 是 | 学科题库 ID |
| `courseId` | int/string | `27` | 是 | 课程 ID |
| `categoryId` | int/string | `135303` / `28102` / `149446` | 是 | 分类节点 ID（章节/知识点/方法） |
| `curPage` | int/string | `1` | 是 | 页码（从 1 开始） |
| `provinceId` | int/string | `-1` | 否 | 地区过滤；`-1` 在页面语义中常表示“全部” |
| `orderBy` | int/string | `2` | 否 | 排序字段（取值口径以页面为准） |
| `quesType` | int/string | `0` | 否 | 题型单选过滤；`0` 常表示“全部” |
| `quesDiff` | int/string | `0` | 否 | 难度单选过滤；`0` 常表示“全部” |
| `quesYear` | int/string | `0` | 否 | 年份单选过滤；`0` 常表示“全部/不限” |
| `paperTypeId` | int/string | `0` | 否 | 题源卷型单选过滤；`0` 常表示“全部” |
| `learngrade` | int/string | `0` | 否 | 年级过滤（编码以站点为准） |
| `term` | int/string | `0` | 否 | 学期过滤（编码以站点为准） |
| `quesAttributeId` | int/string | `0` | 否 | 题目属性过滤（取值集合以站点为准） |

### 3.2 `pageName` 与分类体系的对应关系（观测）

| 分类语义 | 分类路由前缀（常见） | `pageName` 常见取值 |
|---|---|---|
| 章节 | `.../zj{categoryId}/` | `zhangjie` 或 `zj` |
| 知识点 | `.../zsd{categoryId}/` | `zsd` |
| 解题方法 | `.../jtff{categoryId}/` | `jtff` |

### 3.3 多选参数（数组字段）

在抽样中，以下字段可作为多选数组出现：
- `quesTypes`
- `quesDiffs`
- `paperTypeIds`

服务端在样例中可识别的两种表单序列化形式：

1) 重复 key：

```text
quesTypes=2701&quesTypes=2702
paperTypeIds=2&paperTypeIds=6
quesDiffs=1&quesDiffs=2
```

2) `[]` key：

```text
quesTypes[]=2701&quesTypes[]=2702
paperTypeIds[]=2&paperTypeIds[]=6
quesDiffs[]=1&quesDiffs[]=2
```

抽样一致性结果见：`docs/16-question-list-param-validation.md`。

### 3.4 抽样验证：在样例中确实影响 `data.total` 的字段

在 `pageName=zsd&categoryId=28102` 的样例中，以下字段对 `data.total` 有可观察影响（详见 `docs/16-question-list-param-validation.md`）：
- `quesAttributeId`
- `learngrade`
- `term`
- `paperTypeId` / `paperTypeIds`
- `quesDiff` / `quesDiffs`
- `quesTypes`

### 3.5 未确认生效的字段（样例范围内）

- `categoryIds`：在样例中“朴素传参”未表现出对 `total` 的影响；是否需要与其它字段组合属于待验证项。

---

## 4) 响应格式

### 4.1 JSON 结构

典型响应（截断，仅示意字段）：

```json
{
  "code": "0",
  "data": {
    "html": "<div class=\"tk-quest-item ...\" questionid=\"31236198\" ...>...</div> ...",
    "total": 360841
  }
}
```

字段说明：
- `code`：状态码。在不同场景中可观察到字符串或数字形态（实现侧可统一按字符串比较）。
- `data.html`：HTML 片段（题块列表）。
- `data.total`：符合当前筛选条件的集合总量（抽样小集合可闭环核对，见 `docs/16-question-list-param-validation.md`）。

### 4.2 `data.html` 的可观察内容

常见抽取点：
- `questionid="(\\d+)"`：题目 ID（题块根节点属性）
- `/{bankId}p{paperId}.html`：题源试卷链接（若题块包含）
- 题块中可能包含公式图片：`/quesimg/Upload/formula/{hash}.png`（见 `docs/08-formula-mml-latex.md`）

---

## 5) 非目标响应与判别

尽管该端点在抽样中返回 JSON，但仍可能出现非目标响应（例如 `text/html` 的挑战页或登录页）。判别特征见：
- `docs/02-session-cookies-headers.md`
- `docs/troubleshooting.md`

---

## 6) cURL 示例（最小请求）

章节（`pageName=zhangjie`）示例：

```bash
curl.exe "https://zujuan.xkw.com/zujuan-api/question/list" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/gzsx/zj135303/" ^
  --data "pageName=zhangjie&bankId=11&courseId=27&categoryId=135303&provinceId=-1&orderBy=2&quesType=0&quesDiff=0&quesYear=0&curPage=1"
```

知识点（`pageName=zsd`）示例：

```bash
curl.exe "https://zujuan.xkw.com/zujuan-api/question/list" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/gzsx/zsd27925/" ^
  --data "pageName=zsd&bankId=11&courseId=27&categoryId=27925&provinceId=-1&orderBy=2&quesType=0&quesDiff=0&quesYear=0&curPage=1"
```
