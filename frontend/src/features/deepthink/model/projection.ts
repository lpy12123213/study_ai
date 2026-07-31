/**
 * DeepThink 事件 → 运行投影的纯 reducer（与 chat projection 同模式）。
 *
 * 不持有连接对象、不发起 fetch、不显示 toast；输入任务事件，输出新状态。
 * 事件契约镜像后端 DeepThink 流（backend/generation/deepthink）：search_start /
 * node_generated / node_evaluated / node_pruned / node_selected / depth_complete /
 * search_complete / best_path / answer_start / answer_delta / thinking(_delta) /
 * reasoning(_delta) / done / error。
 */
import type { TaskEvent } from "@/shared/api/types";

export type DeepthinkPhase = "idle" | "running" | "done" | "error";

/** 探索节点（镜像后端 ThoughtNode 事件载荷）。 */
export interface DtNode {
  id: string;
  parentId: string | null;
  depth: number;
  thought: string;
  reasoning: string;
  status: string; // pending | evaluated | selected | pruned | final
  isFinal: boolean;
  score: number | null;
  evalReasoning: string;
  issues: string[];
  pruneReason: string;
}

export interface SearchInfo {
  question: string;
  subject: string;
  config?: Record<string, unknown>;
}

export interface DepthInfo {
  depth: number;
  frontierSize: number;
  totalNodes: number;
}

export interface DoneInfo {
  elapsed?: number;
  bestScore?: number;
  totalNodes?: number;
}

export interface DeepthinkProjection {
  phase: DeepthinkPhase;
  stopped: boolean;
  errorMsg: string | null;
  searchInfo: SearchInfo | null;
  depthInfo: DepthInfo | null;
  nodes: DtNode[];
  bestPathIds: Set<string> | null;
  answerStarted: boolean;
  answer: string;
  reasoning: string;
  doneInfo: DoneInfo | null;
}

export type DeepthinkAction =
  /** 开始一次运行：清空运行区并进入 running */
  | { type: "start" }
  /** 全部清空回 idle（新问题） */
  | { type: "clear" }
  /** 中断并返回输入视图（运行数据保留，但不可见） */
  | { type: "back_to_edit" }
  /** 用户手动停止：保留已有内容并进入 done */
  | { type: "stopped" }
  /** 流正常收尾（done 事件未置终态时的兜底） */
  | { type: "stream_done" }
  /** 传输层失败（与 error 事件区分：这里是 fetch/SSE 层面的异常） */
  | { type: "stream_error"; message: string }
  /** 服务端任务事件 */
  | { type: "event"; ev: TaskEvent };

export function initialDeepthinkProjection(): DeepthinkProjection {
  return {
    phase: "idle",
    stopped: false,
    errorMsg: null,
    searchInfo: null,
    depthInfo: null,
    nodes: [],
    bestPathIds: null,
    answerStarted: false,
    answer: "",
    reasoning: "",
    doneInfo: null,
  };
}

function patchNode(nodes: DtNode[], id: string, patch: Partial<DtNode>): DtNode[] {
  return nodes.map((n) => (n.id === id ? { ...n, ...patch } : n));
}

function applyEvent(state: DeepthinkProjection, ev: TaskEvent): DeepthinkProjection {
  const d = (ev.data ?? {}) as Record<string, unknown>;
  switch (ev.type) {
    case "search_start": {
      return {
        ...state,
        searchInfo: {
          question: typeof d.question === "string" ? d.question : "",
          subject: typeof d.subject === "string" ? d.subject : "",
          config: d.config && typeof d.config === "object" ? (d.config as Record<string, unknown>) : undefined,
        },
      };
    }
    case "node_generated": {
      const raw = d.node as Record<string, unknown> | undefined;
      if (!raw || typeof raw.id !== "string") return state;
      const node: DtNode = {
        id: raw.id,
        parentId: typeof raw.parentId === "string" ? raw.parentId : null,
        depth: typeof raw.depth === "number" ? raw.depth : 0,
        thought: typeof raw.thought === "string" ? raw.thought : "",
        reasoning: typeof raw.reasoning === "string" ? raw.reasoning : "",
        status: typeof raw.status === "string" ? raw.status : "pending",
        isFinal: raw.isFinal === true,
        score: null,
        evalReasoning: "",
        issues: [],
        pruneReason: "",
      };
      if (state.nodes.some((n) => n.id === node.id)) return state;
      return { ...state, nodes: [...state.nodes, node] };
    }
    case "node_evaluated": {
      const id = typeof d.nodeId === "string" ? d.nodeId : "";
      if (!id) return state;
      const patch: Partial<DtNode> = { status: "evaluated" };
      if (typeof d.score === "number") patch.score = d.score;
      if (typeof d.evalReasoning === "string") patch.evalReasoning = d.evalReasoning;
      if (Array.isArray(d.issues)) patch.issues = d.issues.map(String);
      return { ...state, nodes: patchNode(state.nodes, id, patch) };
    }
    case "node_pruned": {
      const id = typeof d.nodeId === "string" ? d.nodeId : "";
      if (!id) return state;
      const patch: Partial<DtNode> = {
        status: "pruned",
        pruneReason: typeof d.reason === "string" ? d.reason : "",
      };
      if (typeof d.score === "number") patch.score = d.score;
      return { ...state, nodes: patchNode(state.nodes, id, patch) };
    }
    case "node_selected": {
      const id = typeof d.nodeId === "string" ? d.nodeId : "";
      if (!id) return state;
      return { ...state, nodes: patchNode(state.nodes, id, { status: "selected" }) };
    }
    case "depth_complete": {
      return {
        ...state,
        depthInfo: {
          depth: typeof d.depth === "number" ? d.depth : 0,
          frontierSize: typeof d.frontierSize === "number" ? d.frontierSize : 0,
          totalNodes: typeof d.totalNodes === "number" ? d.totalNodes : 0,
        },
      };
    }
    case "search_complete": {
      const id = typeof d.nodeId === "string" ? d.nodeId : "";
      if (!id) return state;
      return { ...state, nodes: patchNode(state.nodes, id, { status: "final" }) };
    }
    case "best_path": {
      const ids = new Set<string>();
      if (Array.isArray(d.path)) {
        for (const item of d.path) {
          const nodeId = (item as Record<string, unknown> | null)?.nodeId;
          if (typeof nodeId === "string") ids.add(nodeId);
        }
      }
      return { ...state, bestPathIds: ids };
    }
    case "answer_start": {
      return { ...state, answerStarted: true };
    }
    case "answer_delta": {
      const chunk = typeof d.content === "string" ? d.content : "";
      if (!chunk) return state;
      return { ...state, answer: state.answer + chunk };
    }
    case "thinking":
    case "thinking_delta":
    case "reasoning":
    case "reasoning_delta": {
      const chunk = typeof d.content === "string" ? d.content : typeof d.text === "string" ? d.text : "";
      if (!chunk) return state;
      return { ...state, reasoning: state.reasoning + chunk };
    }
    case "done": {
      return {
        ...state,
        doneInfo: {
          elapsed: typeof d.elapsed === "number" ? d.elapsed : undefined,
          bestScore: typeof d.bestScore === "number" ? d.bestScore : undefined,
          totalNodes: typeof d.totalNodes === "number" ? d.totalNodes : undefined,
        },
        phase: "done",
      };
    }
    case "error": {
      const raw =
        typeof d.message === "string" ? d.message : typeof d.error === "string" ? d.error : "解题失败，请重试";
      return {
        ...state,
        errorMsg: raw === "llm_not_configured" ? "未配置 LLM 服务，请先在设置页配置模型后再试" : raw,
        phase: "error",
      };
    }
    default:
      // step / ping / progress 等信封事件与本页无关
      return state;
  }
}

export function deepthinkProjectionReducer(
  state: DeepthinkProjection,
  action: DeepthinkAction,
): DeepthinkProjection {
  switch (action.type) {
    case "start":
      return { ...initialDeepthinkProjection(), phase: "running" };
    case "clear":
      return initialDeepthinkProjection();
    case "back_to_edit":
      return { ...state, phase: "idle" };
    case "stopped":
      return { ...state, stopped: true, phase: "done" };
    case "stream_done":
      return state.phase === "running" ? { ...state, phase: "done" } : state;
    case "stream_error":
      return { ...state, errorMsg: action.message, phase: "error" };
    case "event":
      // 事件只在运行中改变投影（终态/编辑态下的残留帧忽略）
      return state.phase === "running" ? applyEvent(state, action.ev) : state;
    default:
      return state;
  }
}
