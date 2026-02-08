# Python `requests` 示例（访客态）

更新时间：2026-02-08

本文件给出若干最小函数示例，用于：
- 在访客态调用 `paper/list` / `question/list` / `category/child_node`
- 从返回的 HTML 片段中抽取 `paperId/questionId`

示例依赖：`requests`

```python
import requests
```

---

## 1) 通用 Session 与请求头

```python
import requests

BASE = "https://zujuan.xkw.com"


def new_session(referer: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": referer,
        }
    )
    return s
```

---

## 2) `paper/list`：分页拉取并抽取 `paperId`

```python
import re


def fetch_paper_page(bank_id: int, page: int = 1):
    s = new_session(f"{BASE}/shijuan/")
    resp = s.post(
        f"{BASE}/zujuan-api/paper/list",
        data={
            "pageName": "shijuan",
            "bankId": str(bank_id),
            "learnGradeId": "0",
            "paperTypeId": "0",
            "schoolId": "0",
            "provinceId": "-1",
            "paperYear": "0",
            "paperLevelId": "0",
            "newCategoryId": "0",
            "isFreshPaper": "0",
            "orderBy": "0",
            "curPage": str(page),
        },
        allow_redirects=False,
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    html = payload["data"]["html"]

    # /{bankId}p{paperId}.html
    paper_ids = sorted(set(int(x) for x in re.findall(rf"/{bank_id}p(\\d+)\\.html", html)))
    return paper_ids, payload["data"]["total"]
```

---

## 3) `question/list`：分页拉取并抽取 `questionId`

```python
import re


def fetch_question_page(bank_id: int, course_id: int, category_id: int, page: int = 1):
    # 示例以章节路由构造 Referer；知识点/方法场景对应替换为 /zsd{categoryId}/ 或 /jtff{categoryId}/。
    referer = f"{BASE}/gzsx/zj{category_id}/"
    s = new_session(referer)

    resp = s.post(
        f"{BASE}/zujuan-api/question/list",
        data={
            # 常见取值：章节 zhangjie/zj；知识点 zsd；方法 jtff。
            "pageName": "zhangjie",
            "bankId": str(bank_id),
            "courseId": str(course_id),
            "categoryId": str(category_id),
            "provinceId": "-1",
            "orderBy": "2",
            "quesType": "0",
            "quesDiff": "0",
            "quesYear": "0",
            "curPage": str(page),
        },
        allow_redirects=False,
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    html = payload["data"]["html"]

    # questionid="..."
    qids = sorted(set(int(x) for x in re.findall(r'questionid="(\\d+)"', html)))
    return qids, payload["data"]["total"]
```

---

## 4) `category/child_node`：获取子节点列表

```python
def fetch_children(bank_id: int, type_id: int, category_id: int, referer: str):
    s = new_session(referer)
    resp = s.get(
        f"{BASE}/zujuan-api/category/child_node",
        params={
            "bankId": bank_id,
            "type": type_id,
            "categoryId": category_id,
            "c2k": "false",
        },
        allow_redirects=False,
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()  # list[dict]
```

---

## 5) 判别函数：登录页/挑战页（HTML 特征）

列表接口期望返回 JSON；当响应体为 HTML 时，可用以下特征做快速判别。

```python
import requests


def looks_like_login_html(html: str) -> bool:
    return "login.css" in html or "login-popup.css" in html


def looks_like_js_challenge_html(html: str) -> bool:
    if "<body onload=\"check()\">" in html:
        return True
    if "aliyun_waf_aa" in html or "aliyun_waf_bb" in html:
        return True
    if "acw_sc__v2" in html:
        return True
    return False


def looks_like_login_redirect(resp: requests.Response) -> bool:
    # requests 默认会跟随 302；allow_redirects=False 时可直接观察 Location。
    return resp.status_code in (301, 302, 303, 307, 308) and "login" in (resp.headers.get("Location") or "")
```
