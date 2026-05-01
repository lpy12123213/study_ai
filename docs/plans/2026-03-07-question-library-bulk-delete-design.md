# 题库批量删除设计记录

状态：历史记录，能力已并入题库资源接口。

## 当前接口

```http
POST /api/question-library/items/bulk-delete
```

接口用于按题目 ID 批量删除当前用户题库条目。具体请求和返回以 `backend/api/question_library.py` 为准。

## 设计约束

- 只影响当前用户的题库条目。
- 不应误删其他用户数据。
- 是否清理共享题目缓存由后端仓库层决定，不能由前端绕过。
- 前端应在批量操作前给出明确确认。

## 当前落点

- 后端：`backend/api/question_library.py`
- 仓库层：`backend/database/repositories/`
- 前端：`frontend/src/features/questionLibrary/`
