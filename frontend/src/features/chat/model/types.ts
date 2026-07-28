/**
 * 对话轮次只读视图模型（视觉规划 §8.2）。
 * UI 只消费这些投影，不直接解释原始 SSE 事件。
 */

export type ChatRunStatus = "idle" | "streaming" | "done" | "interrupted" | "error" | "stopped";

export interface ThinkingBlockView {
  text: string;
  status: "idle" | "streaming" | "done";
  /** 客户端观察时长（收到首个 thinking_delta 到完成），非模型/服务端权威耗时。 */
  durationMs?: number;
  userVisible: true;
}

export type ToolStepStatus = "queued" | "running" | "success" | "error" | "interrupted" | "stopped";

export interface ToolStepView {
  id: string;
  iteration: number;
  name: string;
  displayName: string;
  /** 一行输入意图摘要（由参数推导，如关键词/表达式）。 */
  intent?: string;
  status: ToolStepStatus;
  arguments?: unknown;
  result?: unknown;
  /** 一行结果摘要（由领域适配器生成）。 */
  summary?: string;
  /** 事件到达时间（客户端观察）；真实执行耗时需后端字段。 */
  observedStartAt?: number;
  observedResultAt?: number;
  /** 服务端权威单工具耗时（tool_result.elapsed_ms）；缺失时回退观察耗时。 */
  serverDurationMs?: number;
  /** 服务端声明的执行方式（tool_start/tool_result.execution_mode）；缺失时不宣称并行关系。 */
  executionMode?: "parallel" | "sequential";
}

export interface ToolIterationView {
  index: number;
  label: string;
  status: ToolStepStatus;
  tools: ToolStepView[];
  /** 首个 tool_start 到达时间与最后 tool_result 到达时间（客户端观察）。 */
  startedAt?: number;
  completedAt?: number;
}

export interface ConversationTurnView {
  runStatus: ChatRunStatus;
  /** 最终回答前的可见流式正文（工具决策轮文本 / 最终回答流式过程）。 */
  interimText: string;
  thinking?: ThinkingBlockView;
  iterations: ToolIterationView[];
  finalText: string;
  maxReached?: boolean;
  errorMessage?: string;
}
