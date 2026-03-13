# 反馈记录问题整理

- 总问题数: 190
- 优先级分布: P0 20 条, P1 84 条, P2 86 条
- 分类数: 40

## 分类统计

- 产品-体验: 22 条
- 前端-Bug: 19 条
- 全局-工程化: 12 条
- 后端-Bug: 12 条
- 自学资料-质量: 12 条
- 全局-安全: 11 条
- 组卷-质量: 11 条
- 后端-健壮性: 8 条
- 前端-体验: 7 条
- 后端-安全: 7 条
- 后端-性能: 7 条
- 后端-架构: 7 条
- 自学资料-速度: 7 条
- 自学资料-继续/恢复: 5 条
- 组卷-速度: 4 条
- 自学资料-生图: 4 条
- 全局-测试: 3 条
- 前端-性能: 3 条
- 组卷-体验: 3 条
- 自学资料-LaTeX: 3 条
- 全局-可观测: 2 条
- 前端-工程化: 2 条
- 前端-接口: 2 条
- AI出题-体验: 1 条
- AI出题-审核流: 1 条
- 全局-接口: 1 条
- 全局-文档: 1 条
- 全局-配置: 1 条
- 前端-a11y: 1 条
- 前端-安全: 1 条
- 前端-架构: 1 条
- 前端-配置: 1 条
- 后端-可观测: 1 条
- 后端-接口: 1 条
- 后端-数据隔离: 1 条
- 后端-测试: 1 条
- 自学资料-检索: 1 条
- 题库-导出: 1 条
- 题库-答案展示: 1 条
- 题库-组卷联动: 1 条

## 问题列表

### P0

1. [自学资料-继续/恢复] 继续按钮-重连失败
来源: nextstep.md
问题: 刷新/断线后点继续不再继续输出；前端 activeStream/resumable 清理时机不一致
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx; frontend/src/stores/useConversationStore.ts; backend/study_materials/task_manager.py

2. [自学资料-继续/恢复] 继续按钮-完成后无法迭代
来源: nextstep.md
问题: 当前仅支持流式输出+回放，不支持已完成后触发下一轮改进
涉及文件: backend/api/study_materials.py; backend/study_materials/task_manager.py; frontend/src/pages/StudyMaterialsPage.tsx

8. [自学资料-质量] 资料生成质量过低-迭代次数过少
来源: nextstep.md
问题: 迭代次数固定（通常仅 1 轮），不由质量评估驱动
涉及文件: backend/agent/planner.py; backend/agent/reflector.py; backend/agent/core.py

9. [自学资料-质量] 资料来源覆盖不足
来源: nextstep.md
问题: 部分知识点 web_search 结果少于 3 条即被认为不足，但自动补检索仅限 iteration==0
涉及文件: backend/agent/core.py; backend/agent/tools/content_review.py

24. [组卷-质量] 题干质量评分维度不足
来源: 代码审查
问题: _quality_score 仅检查 stem 长度/unknown_tokens/图片/公式占位符/登录提示，不检查内容相关性
涉及文件: backend/crawler/zujuan_crawler.py

25. [组卷-质量] 组卷无题目内容审查
来源: 代码审查
问题: compose_paper_workflow 和 compose_paper_blueprint 仅按 quality_score 排序选题，不审查题目内容是否匹配需求
涉及文件: backend/paper_compose/workflow.py; backend/crawler/zujuan_crawler.py

44. [自学资料-质量] Agent 自适应策略缺少显式 policy
来源: 代码审查
问题: 自适应检索/迭代停止条件分散在多处（core.py auto_research / reflector / content_review），缺少统一策略层
涉及文件: backend/agent/core.py; backend/agent/reflector.py; backend/agent/tools/content_review.py

77. [后端-Bug] AgentCore 缩进错误导致自学资料不可用
来源: 代码审查
问题: backend/agent/core.py 存在 unexpected indent 导致模块无法导入且自学资料接口与单元测试失败
涉及文件: backend/agent/core.py; backend/tests/test_parallel_group.py; backend/tests/test_text_utils.py

94. [全局-安全] media/proxy 存在 SSRF 风险（可访问内网/云元数据）
来源: 代码审查
问题: api/media/proxy 公开端点仅禁 localhost/127.0.0.1/::1 但允许 10/172.16/192.168/169.254 等私网与重定向，可能被用来探测内网或读取云元数据
涉及文件: backend/api/media.py; backend/api/canvas.py

108. [全局-安全] 多用户数据未隔离存在越权读取风险
来源: 代码审查
问题: 已引入 JWT 登录与多用户（auth/register 与 role）但 conversations/papers/canvas/search_history 等表无 user_id 字段且 API 未按用户过滤；任意登录用户可读取或删除他人数据
涉及文件: backend/database/schema.py; backend/database/alembic; backend/api/conversations.py; backend/api/papers.py; backend/api/canvas.py; backend/api/system.py; backend/tests

129. [前端-Bug] DeepThink 无法取消/停止任务（前端无 Abort）
来源: 代码审查
问题: DeepThinkPage 在 isStreaming 时禁用清空按钮（disabled={isStreaming}），且 frontend/src/api/deepthink.ts 使用 fetchSSE() 启动流式请求但未提供 AbortSignal；用户一旦误触或题目过大只能被迫等待，属于强烈的可感知体验缺陷。
涉及文件: frontend/src/pages/DeepThinkPage.tsx; frontend/src/hooks/useDeepThink.ts; frontend/src/api/deepthink.ts; frontend/src/api/client.ts

138. [后端-可观测] 减少吞异常导致的 silent failure
来源: 项目审阅
问题: 代码中存在大量 except Exception: pass，会掩盖真实错误并让问题表现为“没反应/随机失败”，尤其在爬虫、LLM、导出链路。
涉及文件: backend/app.py; backend/core/llm_client.py; backend/agent; backend/crawler; backend/api

146. [后端-安全] 生成文件下载增加鉴权与归属校验
来源: 项目审阅
问题: GET /media/generated/{filename} 目前不要求登录，拿到文件名即可下载用户生成内容，存在跨用户泄露风险。
涉及文件: backend/api/media.py; backend/database/schema.py; backend/database/repositories

161. [产品-体验] 全局任务中心（跨功能统一管理）
来源: 功能建议
问题: 长耗时任务分散在不同页面与不同 task_manager（组卷/自学资料/教案/DeepThink），用户难以看到“我当前有哪些任务在跑、进度如何、能否取消/重试/继续”。
涉及文件: frontend/src/pages/*(新增); frontend/src/components/layout/HistorySidebar.tsx; backend/api/tasks.py; backend/study_materials/task_manager.py; backend/paper_compose/task_manager.py

162. [产品-体验] 收藏/置顶/标签系统
来源: 功能建议
问题: 当前只能靠侧边栏顺序或记忆查找历史对话/试卷/学习资料，无法快速收藏高价值内容或按主题整理。
涉及文件: frontend/src/components/layout/HistorySidebar.tsx; frontend/src/pages/*; backend/api/conversations.py; backend/api/papers.py; backend/api/study_materials.py; backend/database/schema.py

173. [产品-体验] 表单草稿自动保存与恢复
来源: 功能建议
问题: 用户在组卷/自学资料/教案等页面编辑输入较久，刷新/误关页面会丢失输入与配置，体验挫败。
涉及文件: frontend/src/pages/BlueprintPage.tsx; frontend/src/pages/StudyMaterialsPage.tsx; frontend/src/pages/LessonPlansPage.tsx; frontend/src/stores/*

183. [自学资料-继续/恢复] 失败任务继续仍缺少按失败阶段续跑
来源: 用户需求
问题: 当前 continue API 仅支持 improve/deepen_research/fix_export/skip_export，依赖单份 resume_working_memory；检索失败/聚合失败/写作失败后仍缺少按失败子阶段直接续跑的能力，也没有显式记录 last_failed_step/provider/query 快照。
涉及文件: backend/api/study_materials.py; backend/api/study_materials_schemas.py; backend/study_materials/task_manager.py; backend/agent/core.py

184. [自学资料-检索] web_search 仍以 AI 摘要为主而非网址结果
来源: 用户需求
问题: planner/core 默认强制 include_summary=true；source_synthesis 优先消费 web.summary；generate_outline/generate_study_material 又明确禁止输出 URL，导致用户在流程里更容易看到 AI 归纳而不是可点击的搜索网址结果。
涉及文件: backend/agent/planner.py; backend/agent/core.py; backend/agent/tools/web_search_knowledge.py; backend/agent/tools/source_synthesis.py; backend/agent/tools/aggregation.py; frontend/src/pages/studyMaterials/hooks/useStudyMaterialsController.ts

186. [AI出题-审核流] AI 出题仍是直接入库缺少预览审核
来源: 用户需求
问题: /question-library/generate 在生成后立即 upsert_question_library_items，AiGenerateWorkspace 也明确写着“自动入库”；用户无法先预览、修改或拒绝题目。
涉及文件: backend/api/question_library.py; backend/api/question_library_schemas.py; backend/question_library/task_manager.py; backend/question_library/generation.py; frontend/src/pages/aiGenerate/AiGenerateWorkspace.tsx; frontend/src/pages/questionLibrary/hooks/useQuestionLibraryTasks.ts

188. [题库-组卷联动] 本地试题栏与组卷网导出来源规则未建立
来源: 用户需求
问题: 当前题库只有单题“加入试题篮”按钮与 save_paper 流程，没有“本地试题栏”暂存区；同时 paper/download-link 会对 AI 题拼接 `https://zujuan.xkw.com/q/ai_xxx` 之类无效链接，系统也未阻止 AI 题与组卷网题混装。
涉及文件: frontend/src/pages/questionLibrary/*; frontend/src/pages/aiGenerate/AiGenerateWorkspace.tsx; frontend/src/stores/*; backend/api/question_library.py; backend/api/papers.py; backend/database/repositories/papers.py

### P1

3. [自学资料-继续/恢复] 继续按钮-错误后无法继续
来源: nextstep.md
问题: 导出/生图等非核心步骤失败后用户希望继续只重跑失败阶段或跳过
涉及文件: backend/api/study_materials.py; backend/agent/core.py

5. [自学资料-LaTeX] MD→LaTeX 大概率不完整
来源: nextstep.md
问题: Markdown 过长导致 LLM 输出截断；一次性转换链路任何环节失败感觉未完成
涉及文件: backend/agent/tools/latex_export.py

6. [自学资料-LaTeX] LaTeX 编译依赖缺失时反复 refine 无意义
来源: nextstep.md
问题: 缺少 xelatex 时仍尝试编译和 refine 循环
涉及文件: backend/agent/tools/latex_export.py; backend/agent/core.py

10. [自学资料-质量] Planner 自由度不足
来源: nextstep.md
问题: 当前 Planner 使用 fallback_plan 固定流程或 LLM plan 仅微调，无法自主增删步骤
涉及文件: backend/agent/planner.py

11. [自学资料-质量] synthesize_sources 输出未充分利用
来源: 代码审查
问题: 源简报生成后写作工具可能未充分利用（依赖 working_memory 键名对齐）
涉及文件: backend/agent/tools/source_synthesis.py; backend/agent/tools/study_material_generation.py

12. [自学资料-质量] content_review 启发式过于简单
来源: 代码审查
问题: heuristic 仅检查 web 结果数量（min_web=3/4/5），不检查内容质量/相关性
涉及文件: backend/agent/tools/content_review.py

13. [自学资料-质量] reflector 审查过于宽松
来源: 代码审查
问题: reflector.py 审查 prompt 仅关注结构/逻辑/严谨，不检查来源覆盖/深度/适用条件
涉及文件: backend/agent/reflector.py

16. [自学资料-速度] 整体生成速度慢-串行瓶颈
来源: nextstep.md
问题: 知识点间虽已支持并行（subagent_concurrency），但 LLM 调用链仍有串行段
涉及文件: backend/agent/core.py; backend/agent/planner.py

17. [自学资料-速度] 无效工作-全量重做
来源: nextstep.md
问题: 迭代时重做全部知识点而非仅失败的
涉及文件: backend/agent/core.py; backend/agent/tools/content_review.py

20. [自学资料-生图] 生图工具无法使用-TikZ 路线
来源: nextstep.md
问题: 依赖 xelatex + dvisvgm，Windows 常缺
涉及文件: backend/agent/tools/diagrams.py; backend/agent/tools/plots.py

21. [自学资料-生图] 生图工具无法使用-Seedream 路线
来源: nextstep.md
问题: 依赖 ARK_API_KEY + SEEDREAM_MODEL，受网络/配额影响
涉及文件: backend/agent/tools/diagrams.py

22. [自学资料-生图] 生图失败阻断整次资料生成
来源: nextstep.md
问题: 生图步骤失败时可能导致整次任务失败
涉及文件: backend/agent/core.py; backend/agent/tools/diagram_planning.py

26. [组卷-质量] difficulty 映射粗糙
来源: 代码审查
问题: _difficulty_code 宽松匹配中"难"统一映射为 5（困难），"较难"和"困难"无法区分
涉及文件: backend/crawler/zujuan_crawler.py

27. [组卷-质量] sub_ai_selector 选题 prompt 可改进
来源: 代码审查
问题: select_best_question prompt 过长且难度判断依赖 LLM 理解"难度系数越低越难"这个反直觉逻辑
涉及文件: backend/mcp/sub_ai_selector.py

28. [组卷-质量] 组卷缺少试卷整体平衡性检查
来源: 代码审查
问题: 选题按 slot 独立进行，不检查整卷难度分布/知识点覆盖是否均衡
涉及文件: backend/paper_compose/workflow.py

31. [组卷-体验] 组卷 SSE 无 thinking/reasoning 事件
来源: 代码审查
问题: compose_paper_events 仅输出 step 事件，无 AI 思考过程展示
涉及文件: backend/paper_compose/workflow.py

33. [前端-体验] StudyMaterialsPage 状态过多（30+ useState）
来源: 代码审查
问题: 2200 行单文件组件，状态管理复杂，维护困难
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx

34. [前端-体验] SubAgent 面板切换时步骤列表不保留滚动位置
来源: 代码审查
问题: 切换知识点 tab 后滚动位置重置
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx

37. [后端-架构] AgentCore.run 方法过长（~900 行）
来源: 代码审查
问题: 单个方法包含全部执行逻辑（subagent 调度/export 包装/auto-research/LaTeX retry），难以维护
涉及文件: backend/agent/core.py

38. [后端-架构] Executor 多重继承 18 个 Mixin
来源: 代码审查
问题: Executor 类继承 18 个 ToolsMixin，命名冲突风险高；新增工具需修改继承链
涉及文件: backend/agent/executor.py

40. [后端-健壮性] web_search_knowledge 多层 fallback 嵌套过深
来源: 代码审查
问题: Exa→Metaso→Exa(legacy)→BigModel 四层 fallback 嵌套 try/except，逻辑复杂难以维护
涉及文件: backend/agent/tools/web_search_knowledge.py

41. [后端-健壮性] crawler session/cookie 过期无自动刷新
来源: 代码审查
问题: Playwright cookie 过期后所有请求失败，需手动重新登录
涉及文件: backend/crawler/zujuan_crawler.py

45. [自学资料-质量] 每知识点至少覆盖维度未强制
来源: 代码审查
问题: nextstep.md 要求每 KP 覆盖动机/定义/性质/误区/应用，但 review 未逐维度检查
涉及文件: backend/agent/tools/content_review.py; backend/agent/tools/study_material_generation.py

46. [组卷-质量] 组卷无知识点精准匹配
来源: 代码审查
问题: compose_paper_workflow 使用 keyword 检索，知识点匹配依赖搜索引擎，精度有限
涉及文件: backend/paper_compose/workflow.py; backend/crawler/zujuan_crawler.py

51. [前端-Bug] useSSE hook 无限重连循环
来源: 代码审查
问题: useSSE.ts:46 connect 回调依赖 onMessage/onError/onComplete，这些通常是每次渲染的新引用导致 useEffect 反复触发重连 SSE 流，造成无限循环
涉及文件: frontend/src/hooks/useSSE.ts

52. [前端-Bug] 聊天页面消息滚动强制跳底
来源: 代码审查
问题: ChatPage.tsx:157-161 和 StudyMaterialsPage.tsx:602-605 在 messages 变化时无条件 scrollTop = scrollHeight；用户正在阅读历史消息时也会被强制跳到底部
涉及文件: frontend/src/pages/ChatPage.tsx; frontend/src/pages/StudyMaterialsPage.tsx

55. [前端-Bug] useChat hook 无取消/中止机制
来源: 代码审查
问题: useChat.ts:78-246 的 useChatStream 没有 AbortController 也没有 cleanup 机制；用户导航离开或发送新消息时旧流继续在后台运行，可能污染 message state
涉及文件: frontend/src/hooks/useChat.ts

58. [前端-Bug] Header 导航栏在小屏幕溢出
来源: 代码审查
问题: Header.tsx:66-89 有 7 个横向导航项但无响应式处理（无 overflow-x-auto/隐藏/汉堡菜单），小屏幕上会溢出或被截断
涉及文件: frontend/src/components/layout/Header.tsx

60. [前端-Bug] DraggableDivider 卸载时泄漏事件监听器
来源: 代码审查
问题: StudyMaterialsPage.tsx:275-314 鼠标按下后在 document 上注册 mousemove/mouseup，但如果组件在拖拽中卸载，这些监听器永远不会被移除，且 document.body.style.cursor/userSelect 不会恢复
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx

61. [前端-Bug] 暗色模式下 card 与 background 颜色完全相同
来源: 代码审查
问题: index.css:77-79 暗色模式 --color-background 和 --color-card 都是 oklch(0.13 0.01 260)，导致卡片与背景无法视觉区分
涉及文件: frontend/src/index.css

65. [后端-Bug] auth.py 使用已弃用的 datetime.utcnow()
来源: 代码审查
问题: auth.py:169 create_access_token 中使用 datetime.utcnow() 在 Python 3.12+ 已弃用并产生 DeprecationWarning
涉及文件: backend/auth.py

67. [后端-Bug] chat_service.py 78KB 单文件过大极难维护
来源: 代码审查
问题: chat_service.py 包含系统提示词模板(约200行)、工具定义(约300行)、以及全部对话逻辑，共 1695 行。新增工具或修改提示词极易引入 bug
涉及文件: backend/chat_service.py

68. [后端-Bug] lesson_plan_agent_v2.py 56KB 单文件过大
来源: 代码审查
问题: lesson_plan_agent_v2.py 1375 行包含 LLM 调用、子智能体调度、Markdown/LaTeX/PDF 导出全部逻辑
涉及文件: backend/lesson_plan_agent_v2.py

73. [后端-Bug] database/models.py 1012 行包含全部数据操作逻辑
来源: 代码审查
问题: models.py 同时包含 ORM 模型定义、数据库操作函数（CRUD）、schema 迁移逻辑，共 1012 行。职责混杂
涉及文件: backend/database/models.py

74. [前端-Bug] useTaskStore activeTasks Map 刷新后丢失
来源: 代码审查
问题: useTaskStore.ts:168 partialize 只序列化 checkpoints 不序列化 activeTasks（Map）。页面刷新后 activeTasks 为空 Map 导致进行中的任务步骤全部丢失
涉及文件: frontend/src/stores/useTaskStore.ts

75. [前端-Bug] conversation-storage localStorage 无大小限制会爆满
来源: 代码审查
问题: useConversationStore.ts persist 到 localStorage 无任何大小控制。随使用量增长会超过 localStorage ~5MB 限制导致所有持久化状态写入失败/损坏
涉及文件: frontend/src/stores/useConversationStore.ts

78. [组卷-速度] compose_paper_events 按槽位串行检索导致慢
来源: 代码审查
问题: backend/paper_compose/workflow.py 对每个slot依次调用 crawler.search_by_keyword 并可能多次翻页放宽；总耗时随槽位数线性增长
涉及文件: backend/paper_compose/workflow.py; backend/crawler/zujuan_crawler.py; backend/api/papers.py

80. [组卷-体验] 槽位缺题仍保存试卷缺少明确提示与补齐入口
来源: 代码审查
问题: 某slot检索失败或 selected 少于 requested 时仍继续保存试卷；用户难发现缺口
涉及文件: backend/paper_compose/workflow.py; backend/api/papers.py; frontend/src/pages/BlueprintPage.tsx; frontend/src/hooks/useBlueprint.ts

82. [组卷-质量] 未对质量flags做硬过滤可能选到需登录或公式占位题
来源: 代码审查
问题: workflow 仅用 quality_score 排序筛选未对 quality_flags 做 hard reject；可能选中 login_required_content 或 formula_unconverted 过多题
涉及文件: backend/paper_compose/workflow.py; backend/crawler/zujuan_crawler.py

85. [自学资料-速度] web_search_knowledge 缺少查询缓存导致重复联网
来源: 代码审查
问题: 自动补检索与多轮迭代中同一provider同一query可能重复调用 web_search_knowledge；浪费时间与额度
涉及文件: backend/agent/tools/web_search_knowledge.py; backend/agent/core.py

87. [自学资料-质量] source_synthesis 的facts未进入写作审查链路
来源: 代码审查
问题: source_synthesis 产出 facts 与 confidence 但仅 brief 写入 working_memory；writer 与 reviewer 无法基于关键事实做一致性约束
涉及文件: backend/agent/tools/source_synthesis.py; backend/agent/tools/study_material_generation.py; backend/agent/tools/content_review.py

96. [全局-工程化] start.ps1 后端依赖检测过粗可能漏装或版本漂移
来源: 代码审查
问题: Ensure-BackendDeps 仅以 pip show fastapi 判断是否需要安装 requirements；当 requirements 变更或其他依赖缺失/版本不符时不会自动修复，导致运行时随机报错
涉及文件: start.ps1; requirements.txt

97. [全局-测试] doctor 烟囱检查缺少 unittest 与前端 lint
来源: 代码审查
问题: start.bat doctor 仅 compileall+import+frontend build，不跑 backend 单元测试也不跑 eslint；容易把回归漏过去
涉及文件: start.ps1; backend/tests; frontend/package.json

104. [全局-安全] npm audit 存在高危依赖漏洞
来源: 安全扫描
问题: frontend 的 npm audit 报依赖漏洞（axios high；minimatch high；rollup high；ajv moderate）；存在依赖链 DoS 或构建链路文件写入等风险
涉及文件: frontend/package.json; frontend/package-lock.json

105. [全局-安全] /models/fireworks 未鉴权可被滥用
来源: 代码审查
问题: backend/api/models.py 调用 Fireworks /models 使用服务端 API Key 且 router 未加 require_auth；任何人可触发外部请求消耗配额并探测配置
涉及文件: backend/api/models.py; backend/api/router.py; backend/api/auth.py; backend/tests

107. [全局-安全] /system/search-history 未鉴权可被刷库
来源: 代码审查
问题: backend/api/system.py 的 POST /api/search-history 未鉴权即可写入数据库 search_history 表；可被批量调用造成数据库膨胀与污染
涉及文件: backend/api/system.py; backend/database/schema.py; backend/database/repositories; backend/tests

113. [全局-工程化] start.sh 的 setup/doctor 与 Windows 脚本不一致且检查不充分
来源: 代码审查
问题: start.sh 同样使用 pip show fastapi 作为依赖判定且 doctor 不跑 unittest 与 eslint；与 start.ps1 的改进目标不一致
涉及文件: start.sh; requirements.txt; frontend/package.json; backend/tests

115. [全局-安全] Canvas HTML sanitize 未过滤危险链接协议
来源: 代码审查
问题: backend/api/canvas.py 的 _sanitize_question_html 会重写 <a> href 但未限制协议；可能保留 javascript: 或 data: 等危险链接导致点击触发 XSS 风险
涉及文件: backend/api/canvas.py; backend/tests

119. [全局-安全] 合规说明与实际存储行为不一致
来源: 代码审查
问题: README 与 docs/DEPLOYMENT.md 声称仅存储题目编号不存储题目内容但当前组卷流程会持久化 stem 及可选 answer/analysis 到 SQLite；存在合规与用户预期风险
涉及文件: README.md; docs/DEPLOYMENT.md; backend/paper_compose/workflow.py; backend/database/schema.py; frontend/src

120. [全局-安全] media/proxy 支持 SVG 可能造成 XSS
来源: 代码审查
问题: api/media/proxy 会缓存并原样返回远程 SVG；用户直接打开该 URL 时 SVG 内脚本可能在本站域名下执行并读取 localStorage token 等敏感信息
涉及文件: backend/api/media.py; backend/app.py; backend/tests

122. [全局-安全] media/proxy 可被用作任意文件缓存代理
来源: 代码审查
问题: /api/media/proxy 对非图片 content-type 会落盘为 .bin 并对外提供 FileResponse；公开端点可能被滥用为文件缓存与分发
涉及文件: backend/api/media.py; backend/tests

123. [前端-性能] Chat 流式输出高频 setState/滚动导致卡顿
来源: 代码审查
问题: frontend/src/hooks/useChat.ts 在 text_delta 事件中每个 delta 都 setMessages(prev=>prev.map(...content+delta))；同时 frontend/src/pages/ChatPage.tsx 对 messages 的 useEffect 每次变化都 requestAnimationFrame 滚动到底部。长回答/高频 delta 时会产生大量重渲染与 DOM scroll 写入，用户体感掉帧、CPU 占用高。
涉及文件: frontend/src/hooks/useChat.ts; frontend/src/pages/ChatPage.tsx

125. [后端-性能] 对话消息接口无分页且返回无用 tool 大字段导致加载慢
来源: 代码审查
问题: backend/api/conversations.py 的 GET /conversations/{id}/messages 会一次性返回该对话所有 Message（包含 role=tool 的 JSON 字符串 content、以及带 tool_calls 的 assistant 消息）。但前端实际会过滤掉 tool role 与 tool_calls assistant（frontend/src/api/chat.ts），造成“传输巨大但不可见”。对长对话用户会感知：打开历史慢、占内存、网络耗时高。
涉及文件: backend/api/conversations.py; backend/database/repositories/conversations.py; frontend/src/api/chat.ts; frontend/src/hooks/useChat.ts

126. [后端-性能] Chat 每次请求拼接全量历史+tool 结果，长对话越聊越慢/易超上下文
来源: 代码审查
问题: backend/chat/llm_mixin.py::_build_messages 会把 history 中的 user/assistant/tool 全量拼到 messages 里，再追加当前 user_message。history 来自数据库且包含 tool 结果 JSON 字符串；对话越长，每次调用 LLM 的输入越大，用户会感知响应越来越慢、成本升高，甚至因上下文超限报错。
涉及文件: backend/api/chat.py; backend/chat/llm_mixin.py; backend/database/repositories/conversations.py

127. [后端-性能] chat_service 非工具场景用 sleep 模拟流式造成额外输出延迟
来源: 代码审查
问题: backend/chat/service.py 在“无工具调用且已有最终内容”的分支里按 chunk_size=12 切片并 await asyncio.sleep(0.01) 模拟流式输出。对于 3000 字符文本约 250 次 sleep，额外增加约 2.5s 延迟，用户体感变慢且无收益。
涉及文件: backend/chat/service.py

128. [后端-性能] 试卷详情页加载慢：GET /papers/{id} 强制外部 AI 分析
来源: 代码审查
问题: backend/api/papers.py 的 get_paper_info 每次请求都会 loop.run_in_executor 调用 analyze_paper；analyze_paper 可能调用 OpenRouter（外部网络）且 timeout=30s。用户打开试卷详情会感知：加载慢、不稳定，且同一试卷重复进入会重复分析。
涉及文件: backend/api/papers.py; backend/analysis_service.py; frontend/src/pages/PaperDetailPage.tsx; frontend/src/api/papers.ts

130. [前端-Bug] DeepThink 消息区域强制跳底，用户无法上滑查看历史/思维树
来源: 代码审查
问题: DeepThinkPage 使用 useEffect([messages]) 直接执行 scrollRef.current.scrollTop = scrollHeight；缺少 stick-to-bottom 判断。流式输出时 messages 频繁更新，用户上滑会被反复拉回底部，体验很差。
涉及文件: frontend/src/pages/DeepThinkPage.tsx

131. [前端-性能] DeepThink 节点多时渲染/状态更新开销大导致卡顿
来源: 代码审查
问题: useDeepThink 在 node_generated/node_evaluated 等事件上频繁 setNodes(prev=>({...prev,[id]:...}))，会造成大对象频繁拷贝；ThinkingTree 每次 render 都 Object.values + 重新布局 positions/edges，并对每个节点使用 framer-motion 动画。节点规模上来（数百/上千）会明显卡顿甚至页面无响应。
涉及文件: frontend/src/hooks/useDeepThink.ts; frontend/src/components/deepthink/ThinkingTree.tsx; frontend/src/pages/DeepThinkPage.tsx

132. [后端-Bug] 学科列表存在重复项（高中语文重复）导致下拉体验与key冲突
来源: 代码审查
问题: backend/core/subjects.py 的 COMMON_SUBJECTS 列表包含重复项（高中语文出现两次），get_all_subjects 会按该列表生成 subjects；前端多个页面用 s.id 作为 key（bank_id 相同会重复），会导致下拉列表重复/React key 冲突/选择行为不稳定。
涉及文件: backend/core/subjects.py; backend/api/subjects.py; frontend/src/api/subjects.ts

133. [前端-Bug] Canvas 页面为占位实现：保存无效且固定 1s loading
来源: 代码审查
问题: frontend/src/pages/CanvasPage.tsx 通过 setTimeout 固定等待 1 秒后展示占位文案，保存按钮没有任何 onClick 行为。用户从导航进入“学习画布”会直观认为功能坏/假加载，属于强体验问题。
涉及文件: frontend/src/pages/CanvasPage.tsx; frontend/src/components/layout/Header.tsx

135. [后端-性能] 组卷页首次加载筛选项慢：/subjects/{subject}/filters 触发 Playwright/抓取需缓存预热
来源: 代码审查
问题: backend/api/subjects.py 的 filters 接口会 await get_crawler(subject=...)；首次进入/切换学科可能触发 ZujuanCrawler.initialize（Playwright 初始化 + 网络请求）。用户体感为：下拉筛选项迟迟不出现或长时间转圈，影响首次使用。
涉及文件: backend/api/subjects.py; backend/crawler_manager.py; backend/crawler/zujuan/client.py; frontend/src/hooks/useSubjects.ts

136. [全局-配置] 统一 settings 入口避免散落 dotenv
来源: 项目审阅
问题: 部分模块仍各自 load_dotenv 或手动解析 .env，导致 .env 查找路径与 override 行为不一致，排障成本高。
涉及文件: backend/core/settings.py; backend/auth.py; backend/crawler/auth.py; backend/mcp/exa_web_search.py; backend/crawler/zujuan_crawler.py

137. [后端-架构] question_library worker 可配置启动
来源: 项目审阅
问题: app.lifespan 默认启动题库评分 worker，某些部署/测试或仅使用组卷功能时不需要但仍消耗资源。
涉及文件: backend/app.py; backend/question_library/worker.py

139. [后端-安全] 反向代理部署下获取真实 client IP
来源: 项目审阅
问题: 当前 rate limit 主要依据 request.client.host；部署在 Nginx/Cloudflare 等反向代理后会变成代理 IP，导致误限或完全失效。
涉及文件: backend/app.py; backend/core/settings.py

140. [后端-安全] LLM API Key 覆盖能力增加权限与开关
来源: 项目审阅
问题: 后端支持通过请求头 X-LLM-API-Key/X-Moonshot-API-Key 覆盖第三方 key；在共享部署场景需要明确权限边界与可控开关。
涉及文件: backend/app.py; backend/core/settings.py; docs/DEPLOYMENT.md

142. [全局-工程化] 增加 CI 自动跑关键检查
来源: 项目审阅
问题: 仓库缺少 CI，容易出现跨平台差异或合并后回归（后端测试/前端 lint/build）。
涉及文件: .github/workflows/ci.yml; start.sh; start.ps1

145. [前端-配置] 统一 API_BASE_URL 与部署说明
来源: 项目审阅
问题: 开发依赖 Vite proxy；生产/跨端口/反代部署时 baseURL 与资源 URL 容易不一致，导致 404 或跨域排障成本高。
涉及文件: frontend/src/api/client.ts; frontend/vite.config.ts; README.md

147. [后端-安全] 禁止 user_id 缺失时兜底写入默认用户
来源: 项目审阅
问题: 部分 API 与 repository 在 user_id 缺失时兜底为 \1\"，会掩盖鉴权/数据归属错误并造成数据污染或越权。"
涉及文件: backend/api/conversations.py; backend/api/system.py; backend/database/repositories

150. [后端-安全] 增加 JWT 吊销/版本控制机制
来源: 项目审阅
问题: JWT 目前无法吊销，token 泄露或用户改密后旧 token 仍可用，缺少快速封禁手段。
涉及文件: backend/auth.py; backend/api/auth.py; backend/database/schema.py

155. [前端-接口] 统一文本资源下载封装避免裸 fetch 丢 token
来源: 项目审阅
问题: 部分页面直接 fetch(resourceUrl) 读取 markdown/tex；若后端将资源改为鉴权下载会直接失败且绕开统一 401 处理。
涉及文件: frontend/src/api/client.ts; frontend/src/pages/studyMaterials/hooks/useStudyMaterialsController.ts

163. [产品-体验] 一键复用配置与“再来一次”
来源: 功能建议
问题: 用户完成一次组卷/资料生成后，经常需要微调参数再运行；目前需要手动复制提示词与筛选条件，重复操作多。
涉及文件: frontend/src/pages/BlueprintPage.tsx; frontend/src/pages/StudyMaterialsPage.tsx; frontend/src/stores/*; backend/api/*

164. [产品-体验] 新手引导与交互式示例库
来源: 功能建议
问题: 新用户不知道从哪里开始，输入格式、可选参数、预期输出不明确；只能靠阅读文档或试错。
涉及文件: frontend/src/pages/*; frontend/src/components/shared/*(新增); backend/api/subjects.py; backend/api/system.py

165. [产品-体验] 统一的任务进度条与预计耗时
来源: 功能建议
问题: SSE 虽有 step 事件，但不同页面展示不一致且缺少“还要多久”的体感反馈；用户在等待时容易焦虑或误以为卡住。
涉及文件: frontend/src/hooks/useSSE.ts; frontend/src/components/task/*; backend/api/tasks.py; backend/api/study_materials.py

166. [产品-体验] 任务完成/失败通知
来源: 功能建议
问题: 用户切换到其他页面或后台时容易错过任务完成；失败后也不容易第一时间看到并采取重试。
涉及文件: frontend/src/components/shared/*; frontend/src/components/layout/HistorySidebar.tsx; backend/api/tasks.py

169. [产品-体验] 历史全文搜索与高亮
来源: 功能建议
问题: 侧边栏只能按标题找；想找某次对话里的关键词或某道题的知识点需要手动翻，很耗时。
涉及文件: frontend/src/components/layout/HistorySidebar.tsx; frontend/src/pages/*; backend/api/conversations.py; backend/api/papers.py; backend/api/study_materials.py; backend/database/*

174. [产品-体验] 提示词/参数模板库（可复用可分享）
来源: 功能建议
问题: 很多用户会反复用相同结构的提示词与参数组合，但目前只能手动复制粘贴，难复用也难共享团队最佳实践。
涉及文件: frontend/src/pages/*; frontend/src/components/shared/*(新增); backend/api/system.py; backend/database/schema.py

175. [产品-体验] 导出中心与导出队列
来源: 功能建议
问题: 导出（PDF/Markdown/LaTeX）分散在不同页面且缺少队列管理；导出失败后用户不知道在哪里重试或查看日志。
涉及文件: frontend/src/pages/*(新增); backend/api/media.py; backend/api/tasks.py; backend/agent/tools/latex_export.py

177. [产品-体验] 一键反馈与问题上报（自动带上下文）
来源: 功能建议
问题: 遇到错误或结果不佳时，用户无法方便地把上下文（request_id、参数、事件时间线）提交给维护者，排障成本高。
涉及文件: frontend/src/components/shared/*(新增); frontend/src/api/client.ts; backend/api/system.py; backend/database/schema.py

180. [产品-体验] 错题本与练习生成（从试卷一键加入）
来源: 功能建议
问题: 用户做完试卷后希望沉淀错题并生成针对性练习，但当前缺少闭环，题目只能停留在展示层。
涉及文件: frontend/src/pages/PaperDetailPage.tsx; frontend/src/pages/*; backend/api/papers.py; backend/api/question_library.py; backend/database/schema.py

182. [产品-体验] 智能重试与自愈建议
来源: 功能建议
问题: 任务失败时用户常不知道下一步该做什么（重试？换模型？跳过导出？），需要手动猜测，体验差。
涉及文件: frontend/src/hooks/useSSE.ts; frontend/src/components/task/*; backend/api/tasks.py; backend/api/study_materials.py; backend/paper_compose/workflow.py

185. [自学资料-质量] subagent 写作结构仍带强制模板痕迹
来源: 用户需求
问题: _default_outline_sections 预置了固定章节模板；generate_outline prompt 强制覆盖定义/直观/性质/误区/应用；writer 每节必须按 `#### 标题` 分段写作，agent 难以按知识点特性自主裁剪结构。
涉及文件: backend/agent/tools/study_material_generation.py; backend/agent/planner.py; backend/agent/reflector.py

187. [AI出题-体验] AI 出题任务缺少任务链接与 thinking 展示
来源: 用户需求
问题: 前端已持有 taskId 但 RunPanel 不提供跳转任务中心/任务详情入口；question-library SSE 仅有 progress/step/item_saved/done/error，无 thinking 事件；当前页面也没有复用统一的 TaskProgressHeader。
涉及文件: backend/api/question_library.py; backend/question_library/task_manager.py; frontend/src/pages/aiGenerate/AiGenerateWorkspace.tsx; frontend/src/pages/questionLibrary/RunPanel.tsx; frontend/src/pages/questionLibrary/hooks/useQuestionLibraryTasks.ts; frontend/src/components/task/TaskProgressHeader.tsx

189. [题库-导出] AI 题试题栏缺少直接 DOCX 导出链路
来源: 用户需求
问题: 当前试卷导出仅支持 markdown/latex/pdf，PaperDetailPage 也没有 DOCX 入口；AI 题加入本地试题栏后无法按要求直接下载为 docx。
涉及文件: backend/api/papers.py; backend/paper_compose/export.py; frontend/src/api/papers.ts; frontend/src/pages/PaperDetailPage.tsx; frontend/src/pages/questionLibrary/*

190. [题库-答案展示] 题库答案解析不是点击题目后内联展开/折叠
来源: 用户需求
问题: QuestionDetailPane 只有在 origin===ai 时才显示 answer/analysis，且需要右侧详情面板或弹窗；已有答案的 crawled/local 题也不会在列表中就地展开。
涉及文件: backend/api/question_library.py; backend/api/question_library_schemas.py; frontend/src/pages/questionLibrary/QuestionLibraryCard.tsx; frontend/src/pages/questionLibrary/QuestionListPane.tsx; frontend/src/pages/questionLibrary/QuestionDetailPane.tsx; frontend/src/api/questionLibrary.ts

### P2

4. [自学资料-继续/恢复] 后端重启后恢复任务
来源: nextstep.md
问题: 后端仅内存存储任务，重启后 task_id 不可用
涉及文件: backend/study_materials/task_manager.py

7. [自学资料-LaTeX] LaTeX 分块并行化未实现
来源: 代码审查
问题: convert_markdown_to_latex 分块后仍串行 LLM 调用，大文档慢
涉及文件: backend/agent/tools/latex_export.py

14. [自学资料-质量] 知识类型检测过于简单
来源: 代码审查
问题: _heuristic_knowledge_type 仅用关键词匹配（定理/算法/实验等），容易误判
涉及文件: backend/agent/tools/study_material_generation.py; backend/agent/tools/knowledge_type_detection.py

15. [自学资料-质量] critique_draft 高分时跳过 refine 可能过早
来源: 代码审查
问题: refine_draft 在 critique 高分时自动跳过，但高分阈值可能不合理
涉及文件: backend/agent/tools/refine_draft.py; backend/agent/tools/self_critique.py

18. [自学资料-速度] 模型策略未分层
来源: 代码审查
问题: 所有 LLM 调用使用同一模型，结构化中间层（source_brief/outline）无需最强模型
涉及文件: backend/agent/tools/source_synthesis.py; backend/agent/tools/study_material_generation.py; backend/core/settings.py

19. [自学资料-速度] 耗时统计缺乏聚合
来源: 代码审查
问题: 每步有 elapsed_ms 但无全局聚合（p50/p95/总 token 估算/每 KP 平均耗时）
涉及文件: backend/agent/core.py

23. [自学资料-生图] 生图能力矩阵缺少环境自检
来源: 代码审查
问题: 启动时不检测可用的生图能力（TikZ/Seedream/Matplotlib）
涉及文件: backend/agent/tools/diagrams.py; backend/agent/tools/plots.py

29. [组卷-质量] compose_paper_workflow 无答案/解析获取
来源: 代码审查
问题: 保存试卷时只保存题干/题型/难度/来源，不保存答案和解析
涉及文件: backend/paper_compose/workflow.py; backend/database/models.py

30. [组卷-质量] 组卷历史去重集仅内存加载
来源: 代码审查
问题: _load_used_question_ids 每次组卷重新加载，无持久化策略；大量组卷后可能遗漏
涉及文件: backend/paper_compose/workflow.py; backend/database/models.py

32. [组卷-体验] 组卷结果无导出功能
来源: 代码审查
问题: 保存的试卷仅在前端展示，无 PDF/Word/Markdown 导出
涉及文件: backend/api/papers.py; backend/paper_compose/workflow.py

35. [前端-体验] conversation-storage 无大小限制
来源: 代码审查
问题: useConversationStore persist 到 localStorage 无限增长，可能导致存储超限
涉及文件: frontend/src/stores/useConversationStore.ts

36. [前端-体验] WelcomeScreen 示例仅 4 个且硬编码
来源: 代码审查
问题: 示例主题固定为函数单调性/二次函数最值/受力分析/化学平衡常数
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx

39. [后端-架构] Planner fallback_plan 和 _parse_llm_plan 重复逻辑
来源: 代码审查
问题: 两处都构建类似的步骤链，调整一处容易遗漏另一处
涉及文件: backend/agent/planner.py

42. [后端-健壮性] chat_service 系统 prompt 过长
来源: 代码审查
问题: get_system_prompt 生成的组卷系统提示词约 3000+ 字符，token 开销大
涉及文件: backend/chat_service.py

43. [后端-健壮性] 数据库无迁移机制
来源: 代码审查
问题: database/models.py 使用 create_all 创建表，字段变更需手动处理
涉及文件: backend/database/models.py

47. [组卷-质量] 组卷 relax 策略无上报/可观测
来源: 代码审查
问题: auto relax（增页/降分/关去重）过程仅存在于 relax_trace 但前端不显示
涉及文件: backend/paper_compose/workflow.py; frontend

48. [全局-安全] API 无速率限制
来源: 代码审查
问题: 所有 API 端点无 rate limiting，可能被滥用
涉及文件: backend/app.py

49. [全局-可观测] 缺少结构化日志
来源: 代码审查
问题: 后端大量使用 print() 输出日志，无结构化格式
涉及文件: backend/ 全局

50. [全局-测试] 测试覆盖不足
来源: 代码审查
问题: backend/tests/ 仅有基础测试，agent/tools 和 paper_compose 缺少单元测试
涉及文件: backend/tests/

53. [前端-Bug] ChatPage 附件按钮(Paperclip)无功能
来源: 代码审查
问题: ChatPage.tsx:263-270 有一个 Paperclip 图标按钮但没有 onClick 处理函数，点击无任何效果，是死 UI 元素
涉及文件: frontend/src/pages/ChatPage.tsx

54. [前端-Bug] StudyMaterialsPage WelcomeScreen 示例发送描述而非标题
来源: 代码审查
问题: StudyMaterialsPage.tsx:438 onExampleClick(item.desc) 将描述文本（如'高中数学：定义法与典型例题'）填入输入框；用户期望发送的是知识点标题（如'函数单调性'）
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx

56. [前端-Bug] SettingsPage API Key 保存后完全未被使用
来源: 代码审查
问题: SettingsPage.tsx:37-47 将 key 存入 localStorage('settings_api_key') 但项目中无任何代码读取该值；整个功能是死代码
涉及文件: frontend/src/pages/SettingsPage.tsx

57. [前端-Bug] SettingsPage 用户角色硬编码为'普通用户'
来源: 代码审查
问题: SettingsPage.tsx:103 无论实际角色（admin 等）始终显示 <Badge>普通用户</Badge>
涉及文件: frontend/src/pages/SettingsPage.tsx

59. [前端-Bug] HistorySidebar '继续任务'按钮无效
来源: 代码审查
问题: HistorySidebar.tsx:301 onResume 回调传入空函数 () => {}，点击'继续任务'菜单项无任何效果
涉及文件: frontend/src/components/layout/HistorySidebar.tsx

62. [前端-Bug] LessonPlansPage SubAgentActivity 缺少 failed 状态
来源: 代码审查
问题: LessonPlansPage.tsx:167 类型定义为 'pending' | 'running' | 'completed' 缺少 'failed'；StudyMaterialsPage 中有 'failed'。教案生成中子智能体失败时 UI 无法正确展示失败状态
涉及文件: frontend/src/pages/LessonPlansPage.tsx

63. [前端-Bug] StudyMaterialsPage LaTeX 对话框 Markdown 区域 readOnly 无法手动编辑
来源: 代码审查
问题: StudyMaterialsPage.tsx:2109 Markdown textarea 设置了 readOnly，用户无法手动粘贴/编辑 Markdown 内容只能从列表选择
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx

64. [前端-Bug] resolveApiResourceUrl 在默认配置下不生效
来源: 代码审查
问题: client.ts:36-51 当 API_BASE_URL 为默认值'/api'（相对路径）时 isAbsoluteHttpUrl 返回 false 直接 return value；下载链接如'/api/media/generated/xxx.md'不会被解析为完整 URL。跨端口部署时下载链接会 404
涉及文件: frontend/src/api/client.ts

66. [后端-Bug] auth.py admin 密码每次重启都被覆盖
来源: 代码审查
问题: auth.py:94 + _bootstrap_users:148 当 ADMIN_PASSWORD env 存在时每次启动都 hash_password 生成新 bcrypt hash 并覆盖磁盘已保存的 hash。如果管理员通过 change_user_password 改过密码也会被覆盖回去
涉及文件: backend/auth.py

69. [后端-Bug] database/models.py 使用已弃用的 declarative_base()
来源: 代码审查
问题: models.py:17 使用 sqlalchemy.ext.declarative.declarative_base() 在 SQLAlchemy 2.0+ 已弃用
涉及文件: backend/database/models.py

70. [后端-Bug] app.py serve_spa 返回 dict 而非正式 JSON 响应
来源: 代码审查
问题: app.py:90 当 frontend/dist 不存在时返回裸 dict {"message": "..."}。FastAPI 虽会序列化但无明确 HTTP 状态码（返回 200），应返回 503 或合适的错误码
涉及文件: backend/app.py

71. [后端-Bug] openai_adapter.py 全局 crawler 并发安全问题
来源: 代码审查
问题: openai_adapter.py:51-64 get_crawler 在锁内获取 crawler 引用后返回，但调用方在锁外使用 crawler。并发请求切换学科时 set_subject 可能与正在进行的搜索冲突
涉及文件: backend/openai_adapter.py

72. [后端-Bug] zujuan_crawler.py 手动解析 .env 不可靠
来源: 代码审查
问题: zujuan_crawler.py:91-128 _load_env_login 自己实现了 .env 解析器而不用 python-dotenv；不支持多行值/export 前缀/转义字符/内联注释等
涉及文件: backend/crawler/zujuan_crawler.py

76. [后端-Bug] api/chat.py 对话标题截断用字符数而非显示宽度
来源: 代码审查
问题: chat.py:91 user_message[:30] 按字符数截断，但中文字符显示宽度约为 ASCII 的 2 倍。30 个中文字符的标题会显得很长
涉及文件: backend/api/chat.py

79. [后端-架构] 组卷选题与relax逻辑重复实现易漂移
来源: 代码审查
问题: workflow 与 zujuan_crawler.compose_paper_blueprint 都实现候选拉取排序去重放宽等逻辑；维护成本高且行为可能不一致
涉及文件: backend/paper_compose/workflow.py; backend/crawler/zujuan_crawler.py; backend/tests/test_paper_compose_workflow.py

81. [组卷-速度] 候选拉取总解析完整题干导致公式处理开销大
来源: 代码审查
问题: crawler.search_by_keyword 在 question/list 阶段 parse_content=True 且可能触发公式转换；即使仅用于排序去重也耗时
涉及文件: backend/crawler/zujuan_crawler.py; backend/paper_compose/workflow.py

83. [组卷-速度] compose_paper_blueprint 并发数写死且缺少限速策略
来源: 代码审查
问题: crawler.compose_paper_blueprint slot_concurrency 固定为3在不同网络与配额下不可调且可能触发站点限流
涉及文件: backend/crawler/zujuan_crawler.py; backend/openai_adapter.py; backend/api/crawler_tools.py

84. [组卷-质量] batch_get_question_details 10题上限影响整卷详情获取
来源: 代码审查
问题: zujuan_crawler.batch_get_question_details 固定裁剪10题导致整卷题目详情与答案解析获取无法覆盖
涉及文件: backend/crawler/zujuan_crawler.py; backend/paper_compose/workflow.py

86. [自学资料-速度] browse_web_pages 缺少URL缓存且可能重复抓取
来源: 代码审查
问题: browse_web_pages 每次都重新抓取相同URL且未复用 Exa 已带正文的结果导致重复网络与解析
涉及文件: backend/agent/tools/browse_web_pages.py; backend/agent/tools/web_search_knowledge.py

88. [全局-可观测] 自学资料缺少每知识点质量与成本汇总报告
来源: 代码审查
问题: 当前仅有逐步 tool_result 不易定位哪个知识点sources不足输出截断或token过高
涉及文件: backend/agent/core.py; backend/agent/tools/study_material_generation.py; frontend/src/pages/StudyMaterialsPage.tsx

89. [全局-接口] SSE事件字段命名不统一导致前端复用成本高
来源: 代码审查
问题: 组卷任务使用 type 与 step 与 taskId；自学资料使用 event 与 data 与 task_id；字段混用导致hooks复用困难
涉及文件: backend/api/papers.py; backend/api/study_materials.py; backend/paper_compose/task_manager.py; backend/study_materials/task_manager.py; frontend/src/hooks/useSSE.ts; frontend/src/hooks/useBlueprint.ts

90. [后端-架构] stdio_server与zujuan_crawler单文件过长影响维护与测试
来源: 代码审查
问题: backend/mcp/stdio_server.py 与 backend/crawler/zujuan_crawler.py 单文件过大且职责混杂；改动风险高且难覆盖测试
涉及文件: backend/mcp/stdio_server.py; backend/crawler/zujuan_crawler.py; backend/tests

91. [全局-测试] 缺少record-replay回放机制导致调试与回归慢
来源: 代码审查
问题: 爬虫与LLM依赖外部网络与配额导致问题难稳定复现；单元测试难写且回归慢
涉及文件: backend/crawler; backend/core/llm_client.py; backend/tests

92. [自学资料-速度] 缺少本地知识库复用导致重复网搜与内容不一致
来源: 代码审查
问题: 同主题多次生成仍从外网检索且历史材料不复用导致速度慢且版本不一致
涉及文件: backend/agent/memory.py; backend/agent/tools/study_archive.py; backend/database/models.py

93. [组卷-速度] 缺少题目元数据缓存与复用导致重复抓取
来源: 代码审查
问题: 同一题目多次组卷反复抓取解析；即使数据库已存stem与quality_score仍未用于候选复用
涉及文件: backend/database/models.py; backend/paper_compose/workflow.py; backend/crawler/zujuan_crawler.py

95. [后端-健壮性] media/proxy 缓存无总量或TTL控制可能撑爆磁盘
来源: 代码审查
问题: api/media/proxy 下载内容写入 .local/media 仅限制单文件大小但无总量与过期策略；大量不同URL会无限增长占满磁盘
涉及文件: backend/api/media.py

98. [全局-工程化] pyproject 配置了 Ruff 但未纳入依赖与检查流程
来源: 代码审查
问题: pyproject.toml 已配置 Ruff 规则但 venv 未安装 ruff 且 doctor/CI 未运行，代码风格与导入排序易漂移
涉及文件: pyproject.toml; requirements.txt; start.ps1

99. [前端-工程化] 前端 eslint 存在告警需清零
来源: 代码审查
问题: npm run lint 输出 3 个 warning（react-refresh only-export-components 与 no-unused-vars）长期会掩盖真实问题
涉及文件: frontend/src/components/ui/badge.tsx; frontend/src/components/ui/button.tsx; frontend/src/pages/LoginPage.tsx

100. [前端-工程化] Vite build 提示 chunk 过大需基础拆包
来源: 代码审查
问题: npm run build 输出 chunks larger than 500 kB after minification 警告，可能影响首屏与弱网体验
涉及文件: frontend/vite.config.ts; frontend/src

101. [后端-安全] plot_tools 使用 eval 需补安全回归测试与错误可观测
来源: 代码审查
问题: _safe_eval_expr 使用 eval 执行表达式虽有 AST 白名单但缺少单测防回归；render_2d_plot 对表达式异常直接忽略可能产出空图且无提示
涉及文件: backend/core/plot_tools.py; backend/tests

102. [全局-工程化] mcp_server/server.py 旧入口无法 import 可能为遗留死代码
来源: 代码审查
问题: 在 venv 下执行 python -c \"import mcp_server.server\" 报 ModuleNotFoundError: core，说明该目录与 backend/core 结构不一致且可能已废弃
涉及文件: mcp_server/server.py; README.md

103. [后端-健壮性] study_materials 任务快照过期文件不主动删除可能堆积
来源: 代码审查
问题: StudyMaterialsTaskManager restore 时跳过 TTL 之外的快照但不会删除文件；长期运行可能 .local/study_materials/tasks 堆积
涉及文件: backend/study_materials/task_manager.py; backend/tests

106. [全局-安全] /system/config 未鉴权暴露运行配置摘要
来源: 代码审查
问题: backend/api/system.py 的 GET /api/config 未鉴权即可返回运行配置摘要（虽无密钥但可被用于侦测部署状态）
涉及文件: backend/api/system.py; backend/api/router.py

109. [后端-架构] zujuan client 文件过大且职责混杂影响维护
来源: 代码审查
问题: backend/crawler/zujuan/client.py 体积约 116KB 且包含多类职责（请求会话；cookie；解析；子进程辅助等）；修改风险高且难覆盖测试
涉及文件: backend/crawler/zujuan/client.py; backend/crawler/zujuan/*; backend/tests

110. [全局-工程化] README 引用的 mcp_config.json 缺失
来源: 代码审查
问题: README.md 结构与 MCP 配置示例引用 mcp_config.json 但仓库中不存在该文件；新用户按文档操作会失败
涉及文件: README.md; mcp_config.json

111. [全局-工程化] Docker agent 构建文件路径错误且缺少 requirements-agent.txt
来源: 代码审查
问题: docker-compose.agent.yml 指向 docker/Dockerfile.agent 但该路径不存在；Dockerfile.agent 依赖 requirements-agent.txt 但仓库缺失；导致 compose/build 无法使用
涉及文件: docker-compose.agent.yml; Dockerfile.agent; requirements-agent.txt; README.md

112. [全局-工程化] docker_agent_worker 未接入且 Docker 执行未实现
来源: 代码审查
问题: backend/docker_agent_worker.py 无调用方且 _execute_docker 返回占位错误；同时存在不一致的 docker-compose/Dockerfile 配置
涉及文件: backend/docker_agent_worker.py; docker-compose.agent.yml; Dockerfile.agent; README.md; backend/tests

114. [全局-工程化] README 引用的 docs/SVG_TO_LATEX.md 缺失
来源: 代码审查
问题: README.md 的文档列表包含 docs/SVG_TO_LATEX.md 但仓库 docs 目录内不存在该文件；按文档导航会 404
涉及文件: README.md; docs/

116. [后端-健壮性] Canvas snapshot 无大小限制可能导致数据库膨胀
来源: 代码审查
问题: canvas create/update 接收 snapshot dict 并直接 json.dumps 入库；缺少大小上限与压缩；大 snapshot 可能导致写入慢或 SQLite 文件暴涨
涉及文件: backend/api/canvas.py; backend/api/canvas_schemas.py; backend/database/schema.py; backend/tests

117. [后端-健壮性] 用户输入缺少 max_length 约束可能导致 DoS
来源: 代码审查
问题: ChatRequest.message 与 StudyMaterialsGenerateRequest.query 等字段未设置最大长度；恶意超大请求会导致内存与日志膨胀并拖慢 LLM 与数据库
涉及文件: backend/api/schemas.py; backend/api/study_materials_schemas.py; backend/api/chat.py; backend/api/study_materials.py; backend/tests

118. [全局-工程化] docs/DEPLOYMENT.md 部署步骤过期且路径错误
来源: 代码审查
问题: docs/DEPLOYMENT.md 指导使用 python backend/database/models.py 初始化数据库与 python crawler/zujuan_crawler.py 测试爬虫等步骤但当前代码结构已拆分且这些入口不存在或不可运行
涉及文件: docs/DEPLOYMENT.md; README.md; start.ps1; start.sh; backend/database/

121. [全局-工程化] docs/TROUBLESHOOTING.md 多处排障步骤过期
来源: 代码审查
问题: docs/TROUBLESHOOTING.md 仍指导运行 backend/database/models.py 初始化数据库并建议在 backend/crawler/zujuan_crawler.py 内改选择器与加调试；当前已拆分为 repositories 与 backend/crawler/zujuan/；按文档操作会无效
涉及文件: docs/TROUBLESHOOTING.md; backend/database/; backend/crawler/zujuan/

124. [前端-体验] Chat 刷新后“思考步骤/工具轨迹”丢失
来源: 代码审查
问题: ChatPage 的 TaskTimeline 依赖 message.steps（仅在流式过程中由 useChatStream 维护）。但刷新/重新进入对话时，前端通过 /conversations/{id}/messages 拉历史，frontend/src/api/chat.ts 会过滤 tool role 且隐藏带 tool_calls 的 assistant 消息，且历史消息不含 steps 字段，导致用户刷新后看不到之前的工具调用步骤与执行轨迹。
涉及文件: frontend/src/pages/ChatPage.tsx; frontend/src/hooks/useChat.ts; frontend/src/api/chat.ts; backend/api/chat.py; backend/database/repositories/conversations.py

134. [前端-体验] 移动端侧边栏默认展开占空间，需自适应折叠并记忆状态
来源: 代码审查
问题: ManusLayout 默认始终渲染 HistorySidebar，HistorySidebar 初始 isCollapsed=false（宽约260px）。在小屏设备上会显著压缩主内容区，用户需每次手动折叠，影响阅读与输入体验。
涉及文件: frontend/src/components/layout/ManusLayout.tsx; frontend/src/components/layout/HistorySidebar.tsx

141. [后端-性能] /assets 静态资源缓存策略更明确
来源: 项目审阅
问题: /assets 通过 StaticFiles 托管但未显式设置长缓存；生产下可能无法充分利用指纹资源的缓存优势。
涉及文件: backend/app.py

143. [全局-工程化] 引入 pre-commit 统一格式与检查
来源: 项目审阅
问题: 格式化与静态检查依赖手动执行，容易出现导入顺序/格式漂移并增加 review 成本。
涉及文件: .pre-commit-config.yaml; pyproject.toml; frontend/package.json; docs/

144. [全局-文档] 架构文档索引化并标注 legacy
来源: 项目审阅
问题: ARCHITECTURE.md 与实际模块扩展（study_materials/deepthink/question_library 等）可能逐渐脱节，导致新同学难定位入口与边界。
涉及文件: docs/ARCHITECTURE.md; backend/api/router.py; README.md

148. [后端-数据隔离] used_questions 去重策略按用户隔离或显式可配置
来源: 项目审阅
问题: used_questions 表无 user_id，默认全局去重会让不同用户互相影响（A 用过题 B 也被去重）。
涉及文件: backend/database/schema.py; backend/paper_compose/workflow.py; docs/

149. [后端-安全] 统一添加安全响应头中间件
来源: 项目审阅
问题: 目前仅部分下载响应加了 nosniff，其它 API/静态资源缺少常见安全头，容易产生浏览器侧风险与误用。
涉及文件: backend/app.py

151. [后端-接口] 统一错误响应 envelope 与 error code
来源: 项目审阅
问题: 错误返回目前混用 detail 字符串与不同结构，前端难以统一提示与国际化；error_messages.py 未形成约束。
涉及文件: backend/api/error_messages.py; backend/app.py; backend/api/*

152. [后端-性能] media/proxy 复用 HTTP 连接池降低代理开销
来源: 项目审阅
问题: media/proxy 每次请求都新建 httpx.AsyncClient，无法复用连接池，增加 TLS/连接建立开销。
涉及文件: backend/api/media.py; backend/app.py

153. [后端-测试] repository 支持注入 session 便于事务化测试
来源: 项目审阅
问题: repository 多直接使用全局 async_session_maker 创建/提交，单元测试难以用事务包裹与回滚，导致用例互相污染。
涉及文件: backend/database/repositories/*; backend/tests

154. [前端-架构] 抽象通用“吸底滚动/回到底部”hook 统一流式页体验
来源: 项目审阅
问题: Chat/StudyMaterials/DeepThink 等页面都需要吸底滚动与用户上滑不打断逻辑，目前实现分散且阈值/行为易不一致。
涉及文件: frontend/src/hooks; frontend/src/pages/ChatPage.tsx; frontend/src/pages/studyMaterials/*

156. [前端-安全] Markdown 链接与外链安全属性统一处理
来源: 项目审阅
问题: Markdown 渲染中链接 href 直接使用，跨端口/反代时可能打不开；target=_blank 时缺少 noopener/noreferrer。
涉及文件: frontend/src/pages/studyMaterials/components/MessageBubble.tsx; frontend/src/api/client.ts

157. [前端-a11y] 替换可点击 div 为语义化控件并补 aria-label
来源: 项目审阅
问题: 侧边栏会话项等使用 div+onClick，键盘不可达；部分仅图标按钮缺少可读名称。
涉及文件: frontend/src/components/layout/HistorySidebar.tsx; frontend/src/components/layout/Header.tsx

158. [前端-体验] 统一错误提示组件并支持复制与重试
来源: 项目审阅
问题: 各页面错误提示方式分散（setError+自绘 UI），难以做到一致的可恢复动作与用户可读信息。
涉及文件: frontend/src/components/shared/*; frontend/src/pages/ChatPage.tsx; frontend/src/pages/studyMaterials/*

159. [前端-性能] 长列表虚拟化或降动画防止掉帧
来源: 项目审阅
问题: 消息列表/步骤时间线/侧边栏会话在数据量大时会产生掉帧或卡顿，动画组件会放大问题。
涉及文件: frontend/src/pages/ChatPage.tsx; frontend/src/components/task/*; frontend/src/components/layout/HistorySidebar.tsx

160. [前端-接口] 统一 axios/SSE/fetch 的错误结构与可重试性
来源: 项目审阅
问题: axios 与 fetchSSERequest 目前各自解析错误，页面层再拼字符串，难以统一“需要登录/可重试/限流”等体验。
涉及文件: frontend/src/api/client.ts; frontend/src/hooks/useSSE.ts; frontend/src/hooks/useChat.ts

167. [产品-体验] 跨设备同步个人设置
来源: 功能建议
问题: API key、主题、默认学科、模型偏好、侧边栏折叠等目前多依赖 localStorage；换设备/清缓存就丢失。
涉及文件: frontend/src/pages/SettingsPage.tsx; frontend/src/stores/*; backend/api/system.py; backend/database/schema.py

168. [产品-体验] 全局快捷键与快捷操作面板
来源: 功能建议
问题: 频繁操作（发送、停止、切换面板、打开历史、回到底部）需要鼠标点来点去，效率低。
涉及文件: frontend/src/pages/*; frontend/src/components/shared/*(新增); frontend/src/stores/*

170. [产品-体验] 离线可读与弱网保护
来源: 功能建议
问题: 弱网/断网时页面可能空白或请求失败；用户希望至少能查看最近的资料与试卷。
涉及文件: frontend/src/api/client.ts; frontend/src/stores/*; frontend/src/pages/*

171. [产品-体验] 只读分享链接与二维码
来源: 功能建议
问题: 用户希望把生成的学习资料/试卷分享给同学或老师；目前只能截图或复制粘贴，且缺少权限与过期控制。
涉及文件: frontend/src/pages/*; frontend/src/components/shared/*; backend/api/media.py; backend/api/papers.py; backend/database/schema.py

172. [产品-体验] 学习计划与复习提醒
来源: 功能建议
问题: 生成资料后缺少后续学习闭环：用户不知道如何安排复习与练习，也无法追踪完成情况。
涉及文件: frontend/src/pages/LessonPlansPage.tsx; frontend/src/pages/StudyMaterialsPage.tsx; backend/api/lesson_plan.py; backend/api/system.py; backend/database/schema.py

176. [产品-体验] 批注与标注（资料/试卷/对话）
来源: 功能建议
问题: 用户希望对生成内容做批注（重点/疑问/错误）并快速回看，但目前只能复制到别处处理，难以形成学习沉淀。
涉及文件: frontend/src/pages/*; frontend/src/components/shared/*; backend/api/system.py; backend/database/schema.py

178. [产品-体验] 可访问性与显示偏好设置（字体/密度/对比度）
来源: 功能建议
问题: 不同设备与视力习惯下，固定字号/行距/对比度会影响阅读与长时间使用；目前缺少统一的可访问性偏好。
涉及文件: frontend/src/pages/SettingsPage.tsx; frontend/src/index.css; frontend/src/stores/*; backend/api/system.py

179. [产品-体验] 个人学习数据面板
来源: 功能建议
问题: 用户使用后缺少“我学了什么/花了多久/效果如何”的反馈闭环，不利于长期留存与复用。
涉及文件: frontend/src/pages/*(新增); backend/api/system.py; backend/database/repositories/*

181. [产品-体验] 结果对比与变更高亮（两次生成差异）
来源: 功能建议
问题: 用户迭代优化同一主题时难以快速看出“这次相比上次改了什么”，只能人工比对，效率低。
涉及文件: frontend/src/pages/StudyMaterialsPage.tsx; frontend/src/pages/PaperDetailPage.tsx; backend/api/study_materials.py; backend/api/papers.py

