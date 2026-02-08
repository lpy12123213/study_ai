# API: `POST /zujuan-api/paper/list`（试卷列表分页）

更新时间：2026-02-08

## 1) 基本信息

- 方法：`POST`
- URL：`https://zujuan.xkw.com/zujuan-api/paper/list`
- 认证：访客态可用（不要求登录）
- 请求体：`application/x-www-form-urlencoded; charset=UTF-8`
- 响应：JSON（抽样响应 `Content-Type` 常为 `application/json; charset=utf-8`）

用途（语义层面）：
- 分页获取试卷列表。
- 返回体中的 `data.html` 为 HTML 片段，包含若干条试卷条目，条目中通常包含 `/{bankId}p{paperId}.html` 链接与标题等文本。

相关文档：
- 片段结构与 ID 抽取：`docs/pages/list-html-fragments.md`
- 试卷详情页：`docs/pages/paper-detail.md`

---

## 2) 请求头（观测到的典型形态）

抽样可用请求中，常见请求头包括：

| Header | 示例值（仅示意） | 说明 |
|---|---|---|
| `Content-Type` | `application/x-www-form-urlencoded; charset=UTF-8` | POST 表单编码 |
| `X-Requested-With` | `XMLHttpRequest` | 前端 AJAX 常见标识 |
| `Referer` | `https://zujuan.xkw.com/shijuan/` | 前端请求通常携带来源页面 |
| `User-Agent` | `Mozilla/5.0 ...` | UA 形态可能影响响应类型（见 `docs/troubleshooting.md`） |

---

## 3) 表单参数

### 3.1 参数表（常见字段）

下表列出前端脚本与抽样请求中出现的常见字段。字段是否对筛选结果生效，以接口返回为准。

| 参数 | 类型 | 常见取值/默认 | 说明 |
|---|---|---|---|
| `pageName` | string | `shijuan` | 页面语义标识（试卷列表常见为 `shijuan`） |
| `bankId` | int/string | `11` | 学科题库 ID |
| `curPage` | int/string | `1` | 页码（从 1 开始） |
| `learnGradeId` | string/int | `0` | 年级/学段过滤（编码以站点为准） |
| `paperTypeId` | int/string | `0` | 卷型/来源类型过滤（编码以站点为准） |
| `paperTypeIds` | int[] | 例如 `2,6` | 多选卷型（数组字段；序列化规则同 `question/list`） |
| `schoolId` | int/string | `0` | 学校过滤（学校 ID 可由 `schools` 接口检索） |
| `provinceId` | int/string | `-1` | 地区过滤；`-1` 在页面语义中常表示“全部” |
| `paperYear` | int/string | `0` | 年份过滤；`0` 常表示“全部/不限” |
| `paperLevelId` | int/string | `0` | 级别过滤（编码以站点为准） |
| `paperDiffId` | int/string | `0` | 难度过滤（页面若提供） |
| `newCategoryId` | int/string | `0` | 分类过滤字段（语义需结合页面与返回） |
| `paperAssist` | int/string | `0` | 辅助过滤字段（站点内部字段） |
| `isFreshPaper` | int/string | `0` | 是否“最新”（编码以站点为准） |
| `orderBy` | int/string | `0` | 排序字段（编码以页面为准） |
| `startTime` | string | `""` | 时间范围（格式以页面为准） |
| `endTime` | string | `""` | 时间范围（格式以页面为准） |
| `tag` | string | `""` | 标签过滤（语义需结合页面与返回） |

### 3.2 多选数组参数的序列化

若使用 `paperTypeIds` 等数组字段，表单编码可采用：
- 重复 key：`paperTypeIds=2&paperTypeIds=6`
- `[]` key：`paperTypeIds[]=2&paperTypeIds[]=6`

该序列化规则在 `question/list` 的样例中已验证可被识别；`paper/list` 的数组字段行为以实时返回为准。

---

## 4) 响应格式

### 4.1 JSON 结构

典型响应（截断，仅示意字段）：

```json
{
  "code": "0",
  "data": {
    "html": "<ul class=\"exam-list\"> ... </ul>",
    "total": 156199
  }
}
```

字段说明：
- `code`：状态码。在不同场景中可观察到字符串或数字形态（实现侧可统一按字符串比较）。
- `data.total`：符合当前筛选条件的试卷总数。
- `data.html`：本页试卷列表 HTML 片段。

### 4.2 `data.html` 的抽取点（观测）

片段中通常包含试卷链接：

```text
/{bankId}p{paperId}.html
```

并可能包含标题、年级、地区、题量、浏览量等文本字段（是否出现取决于页面样式）。

---

## 5) 从返回片段抽取 `paperId`

正则样例：

```regex
/(\\d+)p(\\d+)\\.html
```

Python 示例（从 HTML 片段中提取 `paperId` 集合）：

```python
import re

RE_PAPER = re.compile(r"/(\\d+)p(\\d+)\\.html")

def extract_paper_ids(html: str) -> list[int]:
    ids = {int(m.group(2)) for m in RE_PAPER.finditer(html)}
    return sorted(ids)
```

---

## 6) 非目标响应与判别

该端点在抽样中返回 JSON，但仍可能出现非目标响应（例如挑战页/登录页 HTML）。判别特征见：
- `docs/02-session-cookies-headers.md`
- `docs/troubleshooting.md`

---

## 7) cURL 示例（最小请求）

```bash
curl.exe "https://zujuan.xkw.com/zujuan-api/paper/list" ^
  -H "Content-Type: application/x-www-form-urlencoded; charset=UTF-8" ^
  -H "X-Requested-With: XMLHttpRequest" ^
  -H "Referer: https://zujuan.xkw.com/shijuan/" ^
  --data "pageName=shijuan&bankId=11&learnGradeId=0&paperTypeId=0&schoolId=0&provinceId=-1&paperYear=0&paperLevelId=0&newCategoryId=0&isFreshPaper=0&orderBy=0&curPage=1"
```
