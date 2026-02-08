# API 参考索引（访客态）

更新时间：2026-02-08

## 抽样可用（访客态）

- `docs/api/base.md`：`GET /zujuan-api/base`（学段/学科/题型枚举，JS 变量）
- `docs/api/base-province.md`：`GET /zujuan-api/base-province`（省市区枚举，JS 变量）
- `docs/api/paper-list.md`：`POST /zujuan-api/paper/list`（试卷列表分页，JSON + HTML 片段）
- `docs/api/question-list.md`：`POST /zujuan-api/question/list`（试题列表分页，JSON + HTML 片段）
- `docs/api/category-child-node.md`：`GET /zujuan-api/category/child_node`（章节/知识点树，JSON）
- `docs/api/chaptertextbooks.md`：`GET /zujuan-api/chaptertextbooks`（教材导航 HTML 片段，辅助拿章节 ID）
- `docs/api/schools.md`：`GET /zujuan-api/schools`（学校搜索，辅助拿 `schoolId`）
- `docs/api/search-sse.md`：`GET /zujuan-api/search?query=`（SSE：关键词 → 检索入口 URL）

## 抽样可用（补充性端点）

- `docs/api/user.md`：`GET /zujuan-api/user?t=...`（访客/用户信息，易受 Cookie/Referer 影响）
- `docs/api/search-welfare-url.md`：`GET /zujuan-api/search/welfare-url?keyword=`（福利关键词 → 跳转 URL 文本；与爬虫主流程无关）
- `docs/api/operate.md`：`GET /zujuan-api/operate` / `GET /zujuan-api/operates`（运营位/广告配置；与爬虫主流程无关）

## 抽样不可用 / 需要登录或授权（记录用）

- `docs/api/unavailable-or-auth.md`：前端出现过但访客态不可用/需要授权的端点汇总
