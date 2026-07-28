import type { Page, Route } from "@playwright/test";

/**
 * API 拦截 fixture：以当前后端契约形状填充，不依赖后端进程。
 * 形状来源：src/lib/api/types.ts 与 lib/api/* 的请求函数（clean-room：只用当前契约）。
 */

const USER = { user_id: "local-user", username: "演示用户", role: "admin", created_at: "2026-07-01T08:00:00" };

const HEALTH = { status: "healthy", checks: { db: { ok: true }, disk: { ok: true }, llm: { ok: true } } };

const DASHBOARD_STATS = {
  tasks_total: 42,
  completion_rate: 0.86,
  exports_total: 17,
  avg_duration_s: 95,
  tasks_by_type: { chat: 18, paper: 12, study_material: 8, deepthink: 4 },
  top_subjects: [
    { subject: "数学", count: 21 },
    { subject: "物理", count: 12 },
    { subject: "英语", count: 6 },
  ],
};

const CONVERSATIONS = [
  { id: 101, title: "三角函数诱导公式讲解", created_at: "2026-07-24T09:00:00", updated_at: "2026-07-25T15:30:00" },
  { id: 102, title: "数列综合练习与解析", created_at: "2026-07-23T13:00:00", updated_at: "2026-07-24T10:12:00" },
  { id: 103, title: "英语现在完成时用法总结", created_at: "2026-07-22T08:30:00", updated_at: "2026-07-23T18:45:00" },
];

const MESSAGES_101 = {
  conversation: CONVERSATIONS[0],
  messages: [
    { id: 1, role: "user", content: "帮我讲解三角函数的诱导公式，并各给一个例子", created_at: "2026-07-25T15:28:00" },
    {
      id: 2,
      role: "assistant",
      content:
        "## 诱导公式速记\n\n诱导公式的核心是「**奇变偶不变，符号看象限**」。\n\n| 公式 | 结果 |\n| --- | --- |\n| $\\sin(\\pi - \\alpha)$ | $\\sin\\alpha$ |\n| $\\cos(\\pi - \\alpha)$ | $-\\cos\\alpha$ |\n\n**例 1**：求 $\\sin 150°$。\n\n$\\sin 150° = \\sin(180° - 30°) = \\sin 30° = \\frac{1}{2}$\n\n```python\nimport math\nmath.sin(math.radians(150))  # 0.5\n```",
      tool_calls: [{ function: { name: "search_questions" } }, { function: { name: "python_scientific_compute" } }],
      created_at: "2026-07-25T15:29:10",
    },
  ],
};

const TASKS = {
  tasks: [
    {
      id: 7,
      task_id: "task-7",
      task_type: "paper",
      title: "高一数学三角函数单元卷",
      status: "running",
      progress: 64,
      created_at: "2026-07-26T08:00:00",
      updated_at: "2026-07-26T08:12:00",
    },
    {
      id: 6,
      task_id: "task-6",
      task_type: "study_material",
      title: "牛顿第二定律讲义",
      status: "pending_review",
      progress: 100,
      created_at: "2026-07-25T14:00:00",
      updated_at: "2026-07-25T16:20:00",
    },
    {
      id: 5,
      task_id: "task-5",
      task_type: "chat",
      title: "",
      status: "completed",
      progress: 100,
      created_at: "2026-07-24T09:00:00",
      updated_at: "2026-07-24T09:40:00",
    },
  ],
};

const PAPERS = [
  { paper_id: 208, paper_name: "高一数学三角函数单元卷", created_at: "2026-07-25T16:00:00", question_count: 12 },
  { paper_id: 207, paper_name: "物理运动学综合练习", created_at: "2026-07-24T11:00:00", question_count: 8 },
];

const ARCHIVES = {
  items: [
    { id: 31, subject: "物理", topic: "牛顿第二定律", preset: "讲义", created_at: "2026-07-25T16:20:00", updated_at: "2026-07-25T16:20:00" },
    { id: 30, subject: "数学", topic: "二次函数图像与性质", preset: "讲义", created_at: "2026-07-23T10:00:00", updated_at: "2026-07-24T09:00:00" },
  ],
  count: 2,
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

/** 拦截 /api/**：已映射端点返回契约 fixture，未映射返回空对象。
 *  注意：用 pathname 谓词而非 "**\/api/**" glob——后者会误匹配 Vite 的
 *  /src/lib/api/*.ts 模块请求（MIME 被改成 JSON 导致白屏）。 */
export async function stubApi(page: Page) {
  await page.route((url) => url.pathname.startsWith("/api/"), (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;

    if (path === "/api/auth/me") return json(route, USER);
    if (path === "/api/health") return json(route, HEALTH);
    if (path === "/api/dashboard/stats") return json(route, DASHBOARD_STATS);
    if (path === "/api/conversations" && req.method() === "GET") return json(route, CONVERSATIONS);
    if (/^\/api\/conversations\/\d+\/messages/.test(path)) return json(route, MESSAGES_101);
    if (path === "/api/tasks") return json(route, TASKS);
    if (path === "/api/papers") return json(route, PAPERS);
    if (path === "/api/study-archives") return json(route, ARCHIVES);
    if (path === "/api/user-settings") return json(route, { user_id: USER.user_id, settings: {} });
    if (path === "/api/model-settings") return json(route, {});
    if (path === "/api/config") return json(route, {});
    if (path === "/api/blueprints/") return json(route, []);
    if (path === "/api/question-library/items") {
      return json(route, { total: 0, items: [], limit: 20, offset: 0 });
    }
    if (path === "/api/question-library/previews/latest/pending") return json(route, { success: true, preview: null });
    if (path === "/api/question-library/sessions") return json(route, { success: true, sessions: [] });
    if (path === "/api/exports/files") return json(route, { files: [], count: 0 });

    return json(route, {});
  });
}

type StudyMaterialsVisualMode = "running" | "done" | "failed";

/**
 * 在页面脚本加载前替换资料生成 fetch，以真实 ReadableStream 回放当前 SSE 契约。
 * running 模式故意保持连接打开，便于视觉基线稳定停在工具执行中。
 */
export async function stubStudyMaterialsStream(
  page: Page,
  mode: StudyMaterialsVisualMode,
) {
  await page.addInitScript((visualMode) => {
    Date.now = () => 1_800_000_000_000;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const requestUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const url = new URL(requestUrl, window.location.href);
      const isStudyStream =
        url.pathname === "/api/study-materials/generate" ||
        /\/api\/study-materials\/tasks\/[^/]+\/(continue|stream)/.test(
          url.pathname,
        );
      if (!isStudyStream) return nativeFetch(input, init);

      const base = [
        {
          taskId: "visual-materials-1",
          seq: 1,
          type: "task_started",
          data: {
            taskId: "visual-materials-1",
            query: "函数单调性",
            subject: "高中数学",
          },
        },
        {
          taskId: "visual-materials-1",
          seq: 2,
          type: "status",
          data: { content: "正在规划知识结构与检索路径…" },
        },
        {
          taskId: "visual-materials-1",
          seq: 3,
          type: "thinking",
          data: { content: "先拆解定义、判定方法、典型例题与常见误区。" },
        },
        {
          taskId: "visual-materials-1",
          seq: 4,
          type: "tool_call",
          data: {
            step_id: "split-1",
            name: "split_knowledge_points",
            title: "拆分并识别核心知识点",
            arguments: { topic: "函数单调性" },
          },
        },
        {
          taskId: "visual-materials-1",
          seq: 5,
          type: "tool_result",
          data: {
            step_id: "split-1",
            name: "split_knowledge_points",
            success: true,
            elapsed_ms: 820,
            output: {
              knowledge_points: ["定义与判定", "复合函数", "常见误区"],
            },
          },
        },
        {
          taskId: "visual-materials-1",
          seq: 6,
          type: "tool_call",
          data: {
            step_id: "web-1",
            name: "web_search_knowledge",
            title: "联网搜索相关学习资料",
            arguments: { topic: "函数单调性" },
          },
        },
        {
          taskId: "visual-materials-1",
          seq: 7,
          type: "subagent_start",
          data: { knowledge_point: "定义与判定" },
        },
      ];

      const terminal =
        visualMode === "done"
          ? [
              {
                taskId: "visual-materials-1",
                seq: 8,
                type: "tool_result",
                data: {
                  step_id: "web-1",
                  name: "web_search_knowledge",
                  success: true,
                  elapsed_ms: 2640,
                  output: {
                    results: [
                      {
                        title: "函数单调性知识点",
                        url: "https://example.edu/functions",
                      },
                    ],
                  },
                },
              },
              {
                taskId: "visual-materials-1",
                seq: 9,
                type: "subagent_end",
                data: { knowledge_point: "定义与判定" },
              },
              {
                taskId: "visual-materials-1",
                seq: 10,
                type: "workflow_stage",
                data: { stage: "draft" },
              },
              {
                taskId: "visual-materials-1",
                seq: 11,
                type: "done",
                data: {
                  success: true,
                  material: {
                    topic: "函数单调性 · 自学讲义",
                    subject: "高中数学",
                    markdown:
                      "# 函数单调性\n\n## 核心定义\n\n在给定区间内比较任意两点的函数值。\n\n## 典型例题\n\n判断 $f(x)=x^2$ 在不同区间上的单调性。",
                    passed: true,
                    issues: [],
                    md_url: "/api/media/generated/functions.md",
                    pdf_url: "/api/media/generated/functions.pdf",
                  },
                  quality_report: { passed: true, failed_checks: [] },
                },
              },
            ]
          : visualMode === "failed"
            ? [
                {
                  taskId: "visual-materials-1",
                  seq: 8,
                  type: "tool_result",
                  data: {
                    step_id: "web-1",
                    name: "web_search_knowledge",
                    success: false,
                    elapsed_ms: 2640,
                    output: {},
                    error: "来源覆盖不足",
                  },
                },
                {
                  taskId: "visual-materials-1",
                  seq: 9,
                  type: "recovery_available",
                  data: {
                    code: "quality_gate_not_met",
                    stage: "research",
                    recoverable: true,
                    issues: ["来源覆盖不足", "关键结论缺少交叉验证"],
                  },
                },
                {
                  taskId: "visual-materials-1",
                  seq: 10,
                  type: "error",
                  data: {
                    message: "资料研究未通过质量检查",
                    code: "quality_gate_not_met",
                    stage: "research",
                    recoverable: true,
                  },
                },
              ]
            : [];
      const events = [...base, ...terminal];
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          for (const event of events) {
            controller.enqueue(
              encoder.encode(`data: ${JSON.stringify(event)}\n\n`),
            );
          }
          if (visualMode !== "running") {
            controller.enqueue(encoder.encode("data: [DONE]\n\n"));
            controller.close();
          }
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    };
  }, mode);
}

type ChatVisualMode = "thinking" | "tools-running";

/**
 * 在页面脚本加载前替换 Chat fetch，以真实 ReadableStream 回放当前 Chat SSE 契约
 * （视觉规划遗留缺口：流式中态截图）。两种模式都故意保持连接打开：
 * - thinking：思考文本流式进行中；
 * - tools-running：并行工具批（execution_mode=parallel）一完成一执行中。
 */
export async function stubChatStream(page: Page, mode: ChatVisualMode) {
  await page.addInitScript((visualMode) => {
    Date.now = () => 1_800_000_000_000;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const requestUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const url = new URL(requestUrl, window.location.href);
      if (url.pathname !== "/api/chat") return nativeFetch(input, init);

      const thinkingEvents = [
        { type: "stream_start", iteration: 1, phase: "tool_decision" },
        {
          type: "thinking_delta",
          content: "用户想要三角函数的练习题。我先检索题库中匹配的题目，同时联网核对诱导公式的常见考法，",
          iteration: 1,
          phase: "tool_decision",
        },
        {
          type: "thinking_delta",
          content: "再根据检索结果决定是直接讲解还是提出组卷方案。",
          iteration: 1,
          phase: "tool_decision",
        },
      ];

      const toolEvents = [
        ...thinkingEvents,
        {
          type: "assistant",
          content: "我先并行检索题库与网络资料。",
          tool_calls: [
            { id: "c1", type: "function", function: { name: "search_questions", arguments: "{}" } },
            { id: "c2", type: "function", function: { name: "web_search", arguments: "{}" } },
          ],
          iteration: 1,
        },
        {
          type: "tool_start",
          tool_call_id: "c1",
          tool_name: "search_questions",
          arguments: { keyword: "三角函数 诱导公式", limit: 5 },
          iteration: 1,
          execution_mode: "parallel",
        },
        {
          type: "tool_start",
          tool_call_id: "c2",
          tool_name: "web_search",
          arguments: { query: "三角函数 诱导公式 典型例题" },
          iteration: 1,
          execution_mode: "parallel",
        },
        {
          type: "tool_result",
          tool_call_id: "c1",
          tool_name: "search_questions",
          result: {
            success: true,
            total: 24,
            questions: [
              { question_id: "q-101", stem: "求 sin150° 的值", difficulty: "较易" },
              { question_id: "q-102", stem: "化简 cos(π-α)", difficulty: "中等" },
            ],
          },
          iteration: 1,
          execution_mode: "parallel",
          started_at: 1_800_000_000.0,
          finished_at: 1_800_000_001.2,
          elapsed_ms: 1200,
        },
        // c2 故意保持执行中：时间线停在并行分支的中间状态
      ];

      const events = visualMode === "thinking" ? thinkingEvents : toolEvents;
      const encoder = new TextEncoder();
      const stream = new ReadableStream({
        start(controller) {
          for (const event of events) {
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`));
          }
          // 不发送 [DONE]、不 close：保持流式进行中
        },
      });
      return Promise.resolve(
        new Response(stream, {
          status: 200,
          headers: { "Content-Type": "text/event-stream" },
        }),
      );
    };
  }, mode);
}
