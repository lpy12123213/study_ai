# 高考真题区域前端建设计划

## 目标与现状

后端已提供独立的高考真题成员边界：只有存在结构化出处记录的题目才属于 `gaokao` 区，普通题库默认不返回这些题目。本次前端范围为类型、API 客户端与后续 UI 建设计划，页面实现按下述分期推进。

可用契约：

- `GET /api/question-library/items?area=general`：普通题库（默认）。
- `GET /api/question-library/items?area=gaokao`：高考真题区。
- `GET /api/question-library/items?area=all`：管理场景的全量视图。
- `POST /api/question-library/gaokao/items/manual-import`：手动批量导入题目及结构化出处。
- `POST /api/question-library/gaokao/crawl`：按已声明试卷出处爬取并流式返回进度。
- 列表和详情返回 `library_area` 与 `gaokao_source`；出处包含年份、地区、试卷名、卷别、题号、原始链接、备注和核验状态。

## 信息架构

在现有 `/library` 页面内给“题库浏览”增加一级区域切换，而不是新增一套重复页面：

1. `普通题库` 对应 URL `?tab=browse&area=general`。
2. `高考真题` 对应 URL `?tab=browse&area=gaokao`，视觉上使用稳定的“真题区”标识和独立空状态。
3. 区域、筛选、分页继续进入 URL；切换区域时清空页码和已选题目，浏览器前进/后退可恢复。
4. 普通区不显示真题，真题区不混入模拟、竞赛或 AI 生成题；管理员全量视图不作为默认入口暴露。

## 页面与交互分期

### Phase 1：隔离浏览

- 在 `BrowsePanel` 增加区域切换，并把 `area` 纳入 TanStack Query key 与 `LibraryItemsQuery`。
- 真题卡片固定展示“年份 · 地区 · 卷别 · 题号”，详情 Sheet 增加“出处”区块。
- `verified=true` 显示“已核验”；未核验项显示清晰警告，不用颜色替代文字。
- 年份和地区筛选直接复用现有 `year`、`region` 参数；真题区空状态引导到导入入口，不引导 AI 出题。

### Phase 2：来源完整的批量导入

- 新增“导入高考真题”抽屉，支持粘贴结构化 JSON 和逐题表单；提交前在浏览器内预检必填字段、重复 `question_id` 和年份范围。
- 导入预览按试卷分组，逐题显示题号、题干摘要和出处；确认后调用 `libraryApi.importGaokao`。
- 成功后只失效 `area=gaokao` 的查询；失败时保留用户输入并定位到具体条目。
- 不允许只有自由文本“来源”的题进入真题区；年份、地区和试卷名必须齐全。

### Phase 3：试卷级管理

- 按 `exam_year + region + paper_name + paper_variant` 聚合试卷封面卡片，进入后展示题号顺序和缺题提示。
- 增加出处纠错/核验操作与审计信息；来源链接打开前明确显示域名。
- 组卷和练习入口显式携带 `area=gaokao`，避免后续检索回落到普通题库。

## 验收标准

- 默认打开 `/library` 时，网络请求带 `area=general`，真题不会混入普通列表。
- 切换到真题区后请求带 `area=gaokao`，刷新、返回和分页均保持区域状态。
- 卡片与详情展示同一份结构化出处；缺失必填出处的导入在提交前和服务端均被拒绝。
- 至少覆盖区域 URL 状态、Query key 隔离、真题空状态、出处渲染、导入成功与 422 校验失败的 Vitest 用例。
- 完成 `npm run test`、`npm run build`、`npm run lint`，并用 Playwright 截图核对普通区和真题区的视觉区分。
