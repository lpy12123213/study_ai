# 学习画布前端补全（Canvas Frontend） - 实施方案

**优先级**: P1, 新功能/补全已交付后端
**状态**: 已实现（2026-06-08）
**目标**: 把已完整的 `/canvas` 后端接出来——自由布局的题卡/便签看板、乐观并发保存、版本快照与恢复、AI 选题入板。

> 共同事实：路由的 `CanvasPage.tsx` 存在「顶层真实页 vs 子目录死副本」的重复文件，以 `router/index.tsx` 实际 import 的为准。

## Context / 问题描述
后端 `backend/api/canvas.py`（`/canvas` 前缀，30 行）已实现看板 CRUD、版本快照、AI 选题（`pick-questions`，264 行）、题目渲染（`render`，442 行）；但**路由的** `frontend/src/pages/CanvasPage.tsx` 是「学习画布（开发中）」占位页、保存按钮 `disabled`；`frontend/src/api/canvas.ts`（44 行）类型/方法全错（用 `name/data`、`PATCH`、不存在的 `DELETE`，未解包 `{success,...}`）。USER_GUIDE 已把画布当可用功能描述，实际对用户不可见。

## 关键后端契约（已核实，全部 `require_auth` + `user_id` 维度，响应包 `{success, ...}`）
- `GET /canvas/boards?limit=&q=` → `{success, boards: [{id:number, title, subject, revision, created_at, updated_at}]}`（列表无 snapshot）。
- `POST /canvas/boards`（`CanvasBoardCreate`: `title? subject? snapshot?`）→ `{success, board}`，`revision=1`。
- `GET /canvas/boards/{id}` → `{success, board}`，`board.snapshot` 为**已解析对象**。
- `PUT /canvas/boards/{id}`（`CanvasBoardUpdate`: `title? subject? snapshot? expected_revision?`）→ 乐观并发保存；**版本不匹配返回 HTTP 200** `{success:false, conflict:true, server_board}`（前端必须处理这个非错误冲突体）；成功 `{success, board}`。仅当传 `snapshot` 时 `revision` 自增。snapshot 序列化超 `CANVAS_SNAPSHOT_MAX_BYTES`（默认 2MB）→ HTTP 413。
- `GET /canvas/boards/{id}/versions?limit=` → `{success, versions:[{id, board_id, revision, created_at}]}`（无 snapshot）。
- `POST /canvas/boards/{id}/versions`（无 body，快照当前态）→ `{success, version, versions:[...]}`。
- `GET /canvas/boards/{id}/versions/{vid}` → `{success, version:{..., snapshot(已解析)}}`。
- `POST /canvas/boards/{id}/pick-questions`（`requirement` 必填 1–800, `subject? edu_level? count(1–10,默3) limit max_pages`）→ `{success, selected_ids, questions:[{success, question_id, title, meta, stem_html, type, difficulty, knowledge_points, source, url, select_reason}]}`；失败态 HTTP 200 + `{success:false, error}`。
- `GET /canvas/questions/{qid}/render?subject=&edu_level=` → `{success, question:{..., stem_html}}`，限流 60/60s。
- `stem_html` 已服务端净化（去脚本、`<img>` 改走 `/api/media/proxy`），前端用 `dangerouslySetInnerHTML` 渲染。
- **无 restore 端点**：恢复 = `GET version` 取 snapshot → `PUT` 回看板。**无 DELETE 端点**（见下，可选小补）。

## 设计决策
| 决策项 | 选择 | 说明 |
|--------|------|------|
| 画布编辑器 | **轻量自绘看板**（自定义 snapshot 形状），非 tldraw | 后端 snapshot 自由 JSON，由前端定义；tldraw 重且嵌入题目 HTML 需自定义 shape，成本高。tldraw 列为后续替代 |
| 拖拽实现 | 复用已装 `framer-motion` 的 `drag` | 不引入 dnd-kit/react-flow 新依赖 |
| snapshot 形状 | `{version:1, nodes:[{id, kind:'question'|'note', x,y,w,h, ...}]}` | question 节点带 `{question_id,title,stem_html,meta,source,url}`；note 节点带 `{text}` |
| 状态 | 看板态用 `zustand`（已装），服务端用 react-query | 仿既有范式 |
| 冲突处理 | 弹窗「覆盖 / 放弃本地（载入 server_board）」 | 直接用返回的 `server_board` |
| 版本恢复 | 取版本 snapshot → `PUT` 回看板 | 因无 restore 端点 |
| 删除看板 | 可选：后端补 `DELETE /canvas/boards/{id}` | 当前无；v1 可不做删除或补该端点 |

## 实施清单
- [x] 重写 `frontend/src/api/canvas.ts`：对齐服务端类型、解包 `{success,...}`、`PUT`+`expected_revision`、处理 200 冲突体；新增 versions/pick-questions/render 函数
- [x] 新建 `frontend/src/features/canvas/`：`store`（zustand：nodes/dirty/revision）、`hooks`（useBoards/useBoard/useVersions/usePickQuestions）、`components`（CanvasBoard、QuestionCard、NoteCard、BoardToolbar、VersionsDrawer、PickQuestionsPanel、ConflictDialog）
- [x] 重写 `frontend/src/pages/CanvasPage.tsx` 为看板列表（薄壳）；新建看板视图页
- [x] 路由：`routes.config.ts` + `router/index.tsx` 新增 `/canvas/:boardId`（fullscreen）
- [x] 清理未路由的死文件 `frontend/src/pages/canvas/CanvasPage.tsx`
- [x] （可选）后端补 `DELETE /canvas/boards/{id}` + 仓储删除：v1 保持后端无删除端点，前端不暴露删除入口
- [x] Vitest：store 的 dirty/revision/冲突分支；PickQuestionsPanel 渲染
- [x] 端到端验证：本地浏览器完成新建看板、添加便签、保存 revision、保存版本快照冒烟

## 验证
1. 新建看板 → `pick-questions` 拉题成卡 → 拖动 → 保存（PUT，revision+1）。
2. 「保存版本」→ 版本列表 →「恢复」回滚成功。
3. 两个标签页并发保存 → 后者收到 `conflict:true` → 弹窗「覆盖/放弃本地」可用。
4. 刷新后 snapshot 恢复；`stem_html` 图片经 `/api/media/proxy` 正常显示。

## 风险
- snapshot 体积上限 2MB → 卡片过多时提示；题图走代理，避免外链泄漏/混合内容。
- `stem_html` 用 `dangerouslySetInnerHTML`：仅渲染服务端已净化的 `stem_html`，不渲染任意用户输入。
