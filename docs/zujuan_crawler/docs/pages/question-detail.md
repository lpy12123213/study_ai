# 页面：`/{bankId}q{questionId}.html`（试题详情页）

更新时间：2026-02-08

示例：
- `https://zujuan.xkw.com/11q31298690.html`

本页为试题详情页。该页面可能包含比列表题块更完整的 DOM 结构，但其可用性在访客态下与访问上下文相关（可能返回挑战页）。

范围说明：
- 无登录条件下，答案/解析等区域通常不可见或为空（是否公开展示以页面实际为准）。

---

## 1) 可观察的响应类型波动

同一试题 URL 在不同请求上下文下可能返回不同内容：
- 目标响应：业务 HTML（题干、选项、题型等 DOM）
- 非目标响应：挑战页 HTML（例如包含 `<body onload="check()">` 等特征）

挑战页判别特征见：
- `docs/02-session-cookies-headers.md`
- `docs/13-stability-profile.md`

---

## 2) 页面内的关键变量（观测）：`window.quesDetal`

在抽样页面中，HTML `<script>` 常写入一个全局对象（示意截断）：

```html
<script>
  window.quesDetal = {};
  window.quesDetal.status = 0;
  window.quesDetal.quesid = 31298690;
  window.quesDetal.userid = 0;
</script>
```

可观察字段含义：
- `quesid`：题目 ID（与 URL 中的 `questionId` 一致）
- `userid=0`：访客态（未登录）

字段集合与命名可能随站点脚本调整而变化。

---

## 3) HTML 结构（观测）：题目块与内容容器

在抽样页面中，详情页常包含与列表题块相似的 `tk-quest-item` 结构，可用于提取题型、题干与选项等字段。

与登录相关的可观察现象：
- 答案/解析区域可能为“空容器”或被隐藏，并由前端在登录/授权后异步填充。
- 在访客态下，该区域通常不包含可用数据。
