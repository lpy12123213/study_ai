/**
 * Chat SSE 真实事件 fixtures。
 *
 * 来源：2026-07-26 核对的当前后端契约（backend/workspace/chat/service.py、
 * tools_mixin.py、extra_tools.py、tools_spec.py），手工构造，不来自任何历史前端。
 *
 * 契约要点：
 * - 首轮没有 iteration 事件，由 stream_start 隐式开启；第 2 轮起发送 {type:"iteration", round, message}。
 * - 同一 iteration 可能多次 stream_start（工具决策 / 最终回答阶段）。
 * - 整批 tool_start 先发出，执行结束后集中发出 tool_result。
 * - assistant_final 携带 content 与 total_iterations；最大轮数时 content 以「已完成 N 轮操作。」开头。
 * - error 为终态事件；[DONE] 是 transport sentinel，不进入 reducer（fixtures 均不含 [DONE]）。
 */

/** 一条 wire 事件（与后端 yield 的 JSON 对象同形）。 */
export type ChatWireEvent = Record<string, unknown>;

/** 纯文本问答：无工具、无思考。 */
export const simpleTextStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1 },
  { type: "text_delta", content: "二次函数顶点式 " },
  { type: "text_delta", content: "$y=a(x-h)^2+k$ 的顶点坐标是 $(h,k)$。" },
  {
    type: "assistant_final",
    content: "二次函数顶点式 $y=a(x-h)^2+k$ 的顶点坐标是 $(h,k)$。",
    total_iterations: 1,
  },
];

/** 思考 + 两轮串行工具（题库搜索 → Web 搜索 → 最终回答）。 */
export const thinkingSerialToolsStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  { type: "thinking_delta", content: "用户想找数列综合练习题。", iteration: 1 },
  { type: "thinking_delta", content: "先在题库中检索中等难度的数列题。", iteration: 1 },
  {
    type: "assistant",
    content: "好的，我先在题库中搜索数列综合练习题。",
    tool_calls: [
      {
        id: "call_9f3k2",
        type: "function",
        function: {
          name: "search_questions",
          arguments: "{\"keyword\":\"数列综合\",\"edu_level\":\"高中\",\"difficulty\":\"中等\",\"limit\":5}",
        },
      },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_9f3k2",
    tool_name: "search_questions",
    arguments: { keyword: "数列综合", edu_level: "高中", difficulty: "中等", limit: 5 },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_9f3k2",
    tool_name: "search_questions",
    result: {
      success: true,
      keyword: "数列综合",
      count: 2,
      questions: [
        {
          question_id: "q-1001",
          stem: "已知等差数列 $\\{a_n\\}$ 满足 $a_1=1$，$a_3+a_5=14$…",
          difficulty: "中等",
          knowledge: ["等差数列", "通项公式"],
        },
        {
          question_id: "q-1002",
          stem: "设等比数列 $\\{b_n\\}$ 的前 $n$ 项和为 $S_n$…",
          difficulty: "中等",
          knowledge: ["等比数列", "前 n 项和"],
        },
      ],
      trace: { target: 5, filters: { learn_grade_id: 0, order_by: 2 } },
      applied_edu_level: "高中",
    },
    iteration: 1,
  },
  { type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." },
  { type: "stream_start", iteration: 2, phase: "tool_decision" },
  { type: "thinking_delta", content: "题库已有候选，再补充一个高考真题来源做参照。", iteration: 2 },
  {
    type: "assistant",
    content: "已找到 2 道候选题，再检索相关真题来源。",
    tool_calls: [
      {
        id: "call_a71xd",
        type: "function",
        function: { name: "web_search", arguments: "{\"query\":\"高考数学 数列综合题 真题\",\"limit\":3}" },
      },
    ],
    iteration: 2,
  },
  {
    type: "tool_start",
    tool_call_id: "call_a71xd",
    tool_name: "web_search",
    arguments: { query: "高考数学 数列综合题 真题", limit: 3 },
    iteration: 2,
  },
  {
    type: "tool_result",
    tool_call_id: "call_a71xd",
    tool_name: "web_search",
    result: {
      success: true,
      query: "高考数学 数列综合题 真题",
      provider: "tavily",
      answer: "近年全国卷数列题常与函数、不等式综合。",
      results: [
        {
          title: "2025 年全国高考数学试卷评析",
          url: "https://example.edu/gaokao/2025-review",
          snippet: "数列解答题强调通项与求和的综合运用。",
          published_date: "2025-06-10",
        },
        {
          title: "数列综合题备考策略",
          url: "https://example.edu/blog/seq-strategy",
          snippet: "建议按等差等比基础、递推、求和三条线复习。",
          published_date: "",
        },
      ],
      markdown: "### Web search results for 高考数学 数列综合题 真题 (tavily)\n\n近年全国卷数列题常与函数、不等式综合。",
    },
    iteration: 2,
  },
  { type: "iteration", round: 3, message: "AI 正在进行第 3 轮操作..." },
  { type: "stream_start", iteration: 3, phase: "tool_decision" },
  { type: "thinking_delta", content: "信息足够，整理练习题与解析。", iteration: 3 },
  { type: "stream_start", iteration: 3 },
  { type: "text_delta", content: "下面是一道数列综合练习题（改编自题库候选）：\n\n", iteration: 3 },
  { type: "text_delta", content: "**题目** 已知等差数列 $\\{a_n\\}$ 满足 $a_1=1$，$a_3+a_5=14$。", iteration: 3 },
  {
    type: "assistant_final",
    content:
      "下面是一道数列综合练习题（改编自题库候选）：\n\n**题目** 已知等差数列 $\\{a_n\\}$ 满足 $a_1=1$，$a_3+a_5=14$。",
    total_iterations: 3,
  },
];

/** 同一 iteration 并行工具（search_questions + web_search）：tool_start 整批先发，tool_result 集中后发。 */
export const parallelToolsStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  { type: "thinking_delta", content: "需要同时查题库与网络资料。", iteration: 1 },
  {
    type: "assistant",
    content: "我同时检索题库与网络资料。",
    tool_calls: [
      {
        id: "call_p1",
        type: "function",
        function: { name: "search_questions", arguments: "{\"keyword\":\"三角函数\",\"limit\":5}" },
      },
      {
        id: "call_p2",
        type: "function",
        function: { name: "web_search", arguments: "{\"query\":\"三角函数 诱导公式 总结\",\"limit\":3}" },
      },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_p1",
    tool_name: "search_questions",
    arguments: { keyword: "三角函数", limit: 5 },
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_p2",
    tool_name: "web_search",
    arguments: { query: "三角函数 诱导公式 总结", limit: 3 },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_p1",
    tool_name: "search_questions",
    result: { success: true, keyword: "三角函数", count: 3, questions: [], trace: { target: 5 } },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_p2",
    tool_name: "web_search",
    result: {
      success: true,
      query: "三角函数 诱导公式 总结",
      provider: "tavily",
      results: [
        { title: "诱导公式速记", url: "https://example.edu/trig", snippet: "奇变偶不变，符号看象限。", published_date: "" },
      ],
      markdown: "### Web search results for 三角函数 诱导公式 总结 (tavily)",
    },
    iteration: 1,
  },
  { type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." },
  { type: "stream_start", iteration: 2 },
  { type: "text_delta", content: "已汇总题库候选与网络资料，整理如下…" },
  { type: "assistant_final", content: "已汇总题库候选与网络资料，整理如下…", total_iterations: 2 },
];

/** 工具失败：search_questions 返回 success:false，随后模型给出降级回答。 */
export const toolFailureStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  { type: "thinking_delta", content: "先尝试题库检索。", iteration: 1 },
  {
    type: "assistant",
    content: "我先检索题库。",
    tool_calls: [
      {
        id: "call_f1",
        type: "function",
        function: { name: "search_questions", arguments: "{\"keyword\":\"电磁感应\",\"limit\":5}" },
      },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_f1",
    tool_name: "search_questions",
    arguments: { keyword: "电磁感应", limit: 5 },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_f1",
    tool_name: "search_questions",
    result: {
      success: false,
      error: "login_page",
      keyword: "电磁感应",
      login_required: true,
      cookie_expired: true,
      instructions: "题库登录态已失效，请在设置页重新登录组卷网。",
    },
    iteration: 1,
  },
  { type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." },
  { type: "stream_start", iteration: 2 },
  { type: "text_delta", content: "题库当前不可用（登录态失效），我先基于已有知识为你讲解电磁感应…" },
  {
    type: "assistant_final",
    content: "题库当前不可用（登录态失效），我先基于已有知识为你讲解电磁感应…",
    total_iterations: 2,
  },
];

/** 科学计算 + 函数绘图（一轮两工具，含 create 类媒体结果）。 */
export const computeAndPlotStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  {
    type: "assistant",
    content: "我来计算并画出图像。",
    tool_calls: [
      {
        id: "call_c1",
        type: "function",
        function: {
          name: "python_scientific_compute",
          arguments: "{\"code\":\"import sympy as sp\\nx=sp.symbols('x')\\nresult=sp.solve(x**2-5*x+6,x)\",\"purpose\":\"解方程\"}",
        },
      },
      {
        id: "call_c2",
        type: "function",
        function: { name: "plot_function", arguments: "{\"expr\":\"x**2-5*x+6\",\"x_range\":[0,6]}" },
      },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_c1",
    tool_name: "python_scientific_compute",
    arguments: { code: "import sympy as sp\nx=sp.symbols('x')\nresult=sp.solve(x**2-5*x+6,x)", purpose: "解方程" },
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_c2",
    tool_name: "plot_function",
    arguments: { expr: "x**2-5*x+6", x_range: [0, 6] },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_c1",
    tool_name: "python_scientific_compute",
    result: {
      success: true,
      result_repr: "[2, 3]",
      result_type: "list",
      stdout: "",
      warnings: [],
      available_names: ["sp", "x"],
    },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_c2",
    tool_name: "plot_function",
    result: {
      success: true,
      url: "/api/media/generated/plot-abc123.png",
      markdown: "![plot](/api/media/generated/plot-abc123.png)",
      filename: "plot-abc123.png",
      cached: false,
      bytes: 38210,
    },
    iteration: 1,
  },
  { type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." },
  { type: "stream_start", iteration: 2 },
  { type: "text_delta", content: "方程 $x^2-5x+6=0$ 的两根为 $x=2$ 与 $x=3$，图像如下：\n\n![plot](/api/media/generated/plot-abc123.png)" },
  {
    type: "assistant_final",
    content: "方程 $x^2-5x+6=0$ 的两根为 $x=2$ 与 $x=3$，图像如下：\n\n![plot](/api/media/generated/plot-abc123.png)",
    total_iterations: 2,
  },
];

/** 达到最大轮数：5 轮工具调用后 assistant_final 以固定前缀收尾。 */
export const maxIterationsStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  {
    type: "assistant",
    content: "继续检索。",
    tool_calls: [
      { id: "call_m1", type: "function", function: { name: "search_questions", arguments: "{\"keyword\":\"函数\",\"limit\":3}" } },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_m1",
    tool_name: "search_questions",
    arguments: { keyword: "函数", limit: 3 },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_m1",
    tool_name: "search_questions",
    result: { success: true, keyword: "函数", count: 0, questions: [], trace: { target: 3 } },
    iteration: 1,
  },
  { type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." },
  { type: "stream_start", iteration: 2, phase: "tool_decision" },
  {
    type: "assistant",
    content: "扩大范围再试。",
    tool_calls: [
      { id: "call_m2", type: "function", function: { name: "search_questions", arguments: "{\"keyword\":\"函数 应用\",\"limit\":3}" } },
    ],
    iteration: 2,
  },
  {
    type: "tool_start",
    tool_call_id: "call_m2",
    tool_name: "search_questions",
    arguments: { keyword: "函数 应用", limit: 3 },
    iteration: 2,
  },
  {
    type: "tool_result",
    tool_call_id: "call_m2",
    tool_name: "search_questions",
    result: { success: true, keyword: "函数 应用", count: 1, questions: [], trace: { target: 3 } },
    iteration: 2,
  },
  {
    type: "assistant_final",
    content: "已完成 5 轮操作。根据已检索到的内容：题库中与「函数」相关的候选有限，建议放宽筛选条件后重试。",
    total_iterations: 5,
  },
];

/** 终态错误事件。 */
export const terminalErrorStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1 },
  { type: "text_delta", content: "我先" },
  { type: "error", content: "api_error" },
];

/** 中断前缀：流在工具结果返回前被前端 Abort（没有 final / error / [DONE]）。 */
export const interruptedPrefixStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  { type: "thinking_delta", content: "先在题库中搜索…", iteration: 1 },
  {
    type: "assistant",
    content: "我先搜索题库。",
    tool_calls: [
      { id: "call_i1", type: "function", function: { name: "search_questions", arguments: "{\"keyword\":\"导数\",\"limit\":5}" } },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_i1",
    tool_name: "search_questions",
    arguments: { keyword: "导数", limit: 5 },
    iteration: 1,
  },
];

/** 创建试卷工具结果（语义确认后的 create_paper 调用）。 */
export const createPaperStream: ChatWireEvent[] = [
  { type: "stream_start", iteration: 1, phase: "tool_decision" },
  {
    type: "assistant",
    content: "好的，正在按方案创建试卷。",
    tool_calls: [
      {
        id: "call_cp1",
        type: "function",
        function: { name: "create_paper", arguments: "{\"paper_name\":\"数列单元测试\",\"question_ids\":[\"q-1001\",\"q-1002\"]}" },
      },
    ],
    iteration: 1,
  },
  {
    type: "tool_start",
    tool_call_id: "call_cp1",
    tool_name: "create_paper",
    arguments: { paper_name: "数列单元测试", question_ids: ["q-1001", "q-1002"] },
    iteration: 1,
  },
  {
    type: "tool_result",
    tool_call_id: "call_cp1",
    tool_name: "create_paper",
    result: { success: true, paper_id: 208, message: "试卷创建成功，ID: 208" },
    iteration: 1,
  },
  { type: "iteration", round: 2, message: "AI 正在进行第 2 轮操作..." },
  { type: "stream_start", iteration: 2 },
  { type: "text_delta", content: "试卷「数列单元测试」已创建（ID: 208），可在试卷库中查看。" },
  {
    type: "assistant_final",
    content: "试卷「数列单元测试」已创建（ID: 208），可在试卷库中查看。",
    total_iterations: 2,
  },
];
