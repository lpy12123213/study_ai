# 访客态不可用/需要授权端点（前端脚本枚举 + 抽样实测）

更新时间：2026-02-08

本页目的：
- 汇总前端脚本中出现过的 `/zujuan-api/*` 端点。
- 记录其在“访客态（不登录）”下的可观察返回类型（401/403/302/登录页/挑战页等）。

范围边界：
- 本页仅做“可用性标注”，不包含任何绕过登录/验证码/挑战页的实现。

---

## 1) 典型“需要登录/授权”的可观察表现

常见表现包括：
1) 直接返回 `401 Unauthorized` 或 `403`（JSON 或纯文本）。
2) HTTP `200` 但返回 HTML 登录页（`Content-Type: text/html`，包含 `login.css` 等特征）。
3) HTTP `302` 跳转到登录页（响应头 `Location: /login?ReturnUrl=...`）。
4) 返回挑战页 HTML（例如 `<body onload="check()">`、`aliyun_waf_aa`、`acw_sc__v2` 等特征）。

---

## 2) 已抽样实测：访客态不可用（示例）

| 端点 | 方法 | 访客态可观察结果（示例） | 备注 |
|---|---:|---|---|
| `/zujuan-api/question/batch` | POST | `401 Unauthorized` | 批量题目接口 |
| `/zujuan-api/suggest` | POST | `403`（`请求未授权`） | 搜索建议 |
| `/zujuan-api/switch-question-bank` | POST | `403`（`请求未授权`） | 切换学科库 |
| `/zujuan-api/paper/getpaper` | POST | 200 但返回登录页 HTML | 下载/导出相关 |
| `/zujuan-api/check_ques_parse` | POST | 200 但返回登录页 HTML | 解析权限校验 |
| `/zujuan-api/down_ques_info` | GET | 200 但返回登录页 HTML | 下载/记录相关 |
| `/zujuan-api/qrcode` | POST | `403`（`请求未授权`） | 分享二维码 |
| `/zujuan-api/share_paper/get_url` | POST | `302` → `/login?ReturnUrl=...` | 分享试卷 |
| `/zujuan-api/share_paper/create_url` | POST | `302` → `/login?ReturnUrl=...` | 分享试卷（创建链接） |
| `/zujuan-api/getquestype` | GET | `302` → `/login?ReturnUrl=...` | 下载计费/题型价格相关 |
| `/zujuan-api/getuserdownquesnum` | POST | `302` → `/login?ReturnUrl=...` | 用户态数据 |
| `/zujuan-api/output_analysis` | POST | `302` → `/login?ReturnUrl=...` | 导出试卷分析 |
| `/zujuan-api/download/createpaper` | POST | `302` → `/login?ReturnUrl=...` | 下载/导出 |
| `/zujuan-api/download/check_date_threshold` | POST | `302` → `/login?ReturnUrl=...` | 下载阈值检查 |
| `/zujuan-api/download/create_paper_check` | POST | `302` → `/login?ReturnUrl=...` | 下载前置检查 |
| `/zujuan-api/download/create-paper-ppt` | POST | `302` → `/login?ReturnUrl=...` | 导出 PPT |
| `/zujuan-api/topic/check_user_topic_auth` | POST | `302` → `/login?ReturnUrl=...` | 专题/权限校验 |
| `/zujuan-api/xiaoben/add_ques_xiaoben` | POST | `302` → `/login?ReturnUrl=...` | 校本/个人数据 |
| `/zujuan-api/paper/ppt/check` | GET | `404 Not Found` | 前端脚本引用过，但抽样时点不可用 |

---

## 3) 与账号/同步/收藏相关的端点（枚举）

以下端点名称与路径在前端脚本中出现，语义上与登录态/个人数据绑定相关：
- `/zujuan-api/user/archives`
- `/zujuan-api/usertk/*`
- `/zujuan-api/sync_baskets`
- `/zujuan-api/sync_version*`
- `/zujuan-api/use_ques_history`
- `/zujuan-api/save_setting`

---

## 4) 验证码/风控相关端点（枚举）

以下端点名称与路径在前端脚本中出现，语义上与验证码与风险校验流程相关：
- `/zujuan-api/geetest_register`
- `/zujuan-api/verification/register`
- `/zujuan-api/verification/validate`
- `/zujuan-api/getCaptchaCode`
- `/zujuan-api/validateCaptchaCode`
- `/zujuan-api/forbidverificationcheck`

---

## 5) 相关索引

- 可用端点矩阵：`docs/04-api-matrix.md`
