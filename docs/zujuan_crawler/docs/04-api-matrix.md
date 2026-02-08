# 4. API 可用性矩阵（访客态）

更新时间：2026-02-08

说明：
- “访客可用”指：不登录，仅带常规请求头（必要时带 Referer）即可拿到结构化返回
- “需要授权/登录”指：返回 `401/403` 或返回 HTML 登录页，而非你期望的数据
- 站点可能随时调整；本文矩阵仅反映上述日期的抽样验证与观察结果

## 4.1 已验证：访客可用（抽样）

| 接口/页面 | 方法 | 返回 | 用途 |
|---|---:|---|---|
| `/zujuan-api/base` | GET | `var edu=[...]` | 学科/题型等枚举，获得 `bankId/courseId/courseIdPy` |
| `/zujuan-api/base-province` | GET | `var province_list=[...]` | 省市区枚举（`provinceId/areaId`） |
| `/zujuan-api/search?query=` | GET | SSE（`text/event-stream`） | 关键词 → 检索入口 URL（SSE 结束事件中给出） |
| `/zujuan-api/search/welfare-url?keyword=` | GET | `text/plain` | 福利关键词 → 跳转 URL（与试题/试卷列表无直接关系） |
| `/zujuan-api/operate?k=` | GET | `text/plain`（JSON 或 `null`） | 运营位/广告配置（与试题/试卷列表无直接关系） |
| `/zujuan-api/operates?k=` | GET | `text/plain`（JSON 数组） | 同上（批量 key） |
| `/zujuan-api/paper/list` | POST | JSON（`code`,`data.html`,`total`） | 分页拉取试卷列表 |
| `/zujuan-api/question/list` | POST | JSON（`code`,`data.html`,`total`） | 分页拉取试题列表（可筛选） |
| `/zujuan-api/category/child_node` | GET | JSON 数组 | 拉章节/知识点/解题方法树（分片抓取） |
| `https://static.zxxk.com/zujuan/tree/*.json` | GET | JSON（整棵树） | CDN 预生成分类树（部分学科 `j_{bankId}.json` 可能 404） |
| `/zujuan-api/chaptertextbooks` | GET | HTML 片段 | 获取某教材版本的章节导航（辅助拿 chapterId） |
| `/zujuan-api/schools?1=1&keyword=...` | GET | JSON（`code=200`） | 学校搜索（用于 paper/list 的 schoolId） |
| `/sitemap.xml` | GET | XML | sitemap index |
| `/sitemap/p{n}.xml` | GET | XML | paper URL 列表 |

补充说明：
- `/zujuan-api/user?t=...` 在部分场景也可用，但对 Cookie/Referer 更敏感，详见 `docs/api/user.md`
- sitemap（`/sitemap.xml`、`/sitemap/p*.xml`）在部分时段/访问模式下可能返回挑战页（`text/html` + `check()`）。当响应为挑战页时，该入口在该时点不可用于获取 XML；可替代公开入口包括 `paper/list`，或通过浏览器人工下载 sitemap 文件。

## 4.2 前端存在，但访客不可用/需要授权（抽样观察）

这些端点来自前端脚本枚举与少量实测，通常表现为 `401/403` 或直接返回 HTML 登录页：

| 端点 | 方法 | 访客态表现（示例） | 备注 |
|---|---:|---|---|
| `/zujuan-api/question/batch` | POST | `401 Unauthorized` | 批量加入/获取题目（疑似登录态） |
| `/zujuan-api/paper/getpaper` | POST | 200 但返回登录页 HTML | 常用于下载/导出 |
| `/zujuan-api/check_ques_parse` | POST | 200 但返回登录页 HTML | 检查解析权限 |
| `/zujuan-api/down_ques_info` | GET | 200 但返回登录页 HTML | 下载记录/相关 |
| `/zujuan-api/suggest` | POST | `403 请求未授权` | 搜索建议 |
| `/zujuan-api/switch-question-bank` | POST | `403 请求未授权` | 切换学科库 |
| `/zujuan-api/qrcode` | POST | `403 请求未授权` | 分享二维码（前端按钮可见，但访客不可用） |
| `/zujuan-api/share_paper/get_url` | POST | `302` 跳登录 | 分享试卷（基于 `paperXml`），访客会被重定向登录 |
| `/zujuan-api/share_paper/create_url` | POST | `302` 跳登录 | 同上（创建分享链接） |
| `/zujuan-api/getquestype` | GET | `302` 跳登录 | 获取题型/计费信息（前端用于下载计费） |
| `/zujuan-api/getuserdownquesnum` | POST | `302` 跳登录 | 用户态数据（如“最近一年使用次数”） |
| `/zujuan-api/output_analysis` | POST | `302` 跳登录 | 导出试卷分析 |
| `/zujuan-api/download/*` | POST | `302` 跳登录 | 下载/导出相关（createpaper/check/ppt/topic 等） |
| `/zujuan-api/topic/check_user_topic_auth` | POST | `302` 跳登录 | 专题/权限校验（下载流程相关） |
| `/zujuan-api/xiaoben/add_ques_xiaoben` | POST | `302` 跳登录 | 校本/收藏类（账号数据） |
| `/zujuan-api/paper/ppt/check` | GET | `404`（实测） | 前端脚本引用过，但当前对访客不可用/不存在 |

注意：
- 文档只做“可用性标注”，不提供绕过方案。
- 更多“前端出现过但在访客态不可用/需要授权”的端点清单见：`docs/api/unavailable-or-auth.md`
