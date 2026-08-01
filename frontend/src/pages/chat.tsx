import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  Bot,
  CheckCircle2,
  ChevronRight,
  List,
  MessagesSquare,
  Pencil,
  Plus,
  Sparkles,
  Trash2,
  Wrench,
  X,
  XCircle,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { conversationsApi, sendChatMessage } from "@/features/chat/api";
import type { ChatMessage, Conversation } from "@/shared/api/types";
import { formatRelative } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";
import { MarkdownView } from "@/components/markdown/markdown-view";
import { SubjectSelect } from "@/components/question/subject-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { decodeChatEvent } from "@/features/chat/streaming/contract";
import { COMPOSER_MODES } from "@/features/chat/model/composer-modes";
import {
  chatProjectionReducer,
  initialChatProjection,
  type ChatProjectionAction,
  type ChatProjectionState,
  type StreamEndReason,
} from "@/features/chat/model/reducer";
import { selectVisibleText } from "@/features/chat/model/selectors";
import type { ConversationTurnView, ToolStepView } from "@/features/chat/model/types";
import { AssistantTurn } from "@/features/chat/ui/assistant-turn";
import { PromptComposer } from "@/features/chat/ui/prompt-composer";
import { SemanticConfirmation } from "@/features/chat/ui/semantic-confirmation";
import { ToolInspectorHost } from "@/features/chat/ui/tool-inspector-host";

// ---------------- 本地类型与常量 ----------------

/** 流式进行中的本地消息（未落库前渲染用） */
interface LiveUserItem {
  key: string;
  role: "user";
  content: string;
}

interface LiveAssistantItem {
  key: string;
  role: "assistant";
  projection: ChatProjectionState;
}

type LiveItem = LiveUserItem | LiveAssistantItem;

const EXAMPLE_QUESTIONS = [
  "帮我讲解二次函数顶点式的图像与性质",
  "出一道高中数学数列综合练习题并给出解析",
  "物理中瞬时速度和平均速度有什么区别？",
  "帮我总结英语现在完成时的常见用法",
];

function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message || err.code;
  if (err instanceof Error) return err.message;
  return "操作失败，请重试";
}

// ---------------- 局部子组件 ----------------

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-xl rounded-br-md bg-primary px-3.5 py-2.5 text-sm leading-relaxed text-primary-foreground shadow-soft">
        {content}
      </div>
    </div>
  );
}

function AssistantShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
        <Bot className="size-4" />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

/** 历史消息中 assistant 携带的 tool_calls（后端已解析为数组；兼容 JSON 字符串）渲染为小标记 */
function ToolCallsChips({ toolCalls }: { toolCalls?: ChatMessage["tool_calls"] }) {
  const names = useMemo(() => {
    if (!toolCalls) return [] as string[];
    let arr: unknown = toolCalls;
    if (typeof toolCalls === "string") {
      try {
        arr = JSON.parse(toolCalls);
      } catch {
        return [] as string[];
      }
    }
    if (!Array.isArray(arr)) return [] as string[];
    return arr.map((t) => String((t as any)?.function?.name ?? (t as any)?.name ?? "")).filter(Boolean);
  }, [toolCalls]);
  if (names.length === 0) return null;
  return (
    <div className="mb-1.5 flex flex-wrap gap-1.5">
      {names.map((n, i) => (
        <span
          key={`${n}-${i}`}
          className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/60 px-1.5 py-0.5 text-xs text-muted-foreground"
        >
          <Wrench className="size-3" />
          {n}
        </span>
      ))}
    </div>
  );
}

/** 历史消息中的 tool 角色记录（折叠小字） */
function ToolRecordRow({ message }: { message: ChatMessage }) {
  const [open, setOpen] = useState(false);
  const ok = message.tool_result_meta?.success;
  return (
    <div className="pl-9 text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md px-2 py-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
        <Wrench className="size-3" />
        <span>工具调用记录{message.tool_call_id ? ` · ${message.tool_call_id}` : ""}</span>
        {ok === true ? <CheckCircle2 className="size-3 text-success" /> : null}
        {ok === false ? <XCircle className="size-3 text-destructive" /> : null}
      </button>
      {open ? (
        <pre className="ml-6 mt-1 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-muted p-2 font-mono text-xs leading-relaxed text-muted-foreground">
          {message.content}
        </pre>
      ) : null}
    </div>
  );
}

function HistoryRow({ message, highlight = false }: { message: ChatMessage; highlight?: boolean }) {
  let body: ReactNode;
  if (message.role === "user") body = <UserBubble content={message.content} />;
  else if (message.role === "tool") body = <ToolRecordRow message={message} />;
  else if (message.role === "assistant") {
    body = (
      <AssistantShell>
        <ToolCallsChips toolCalls={message.tool_calls} />
        {message.content ? (
          <div className="max-w-[68ch]">
            <MarkdownView content={message.content} />
          </div>
        ) : null}
      </AssistantShell>
    );
  } else {
    body = null;
  }
  return (
    <div data-message-id={message.id} className={cn(highlight && "rounded-lg ring-2 ring-primary/40")}>
      {body}
    </div>
  );
}

/** 流式中的 assistant 轮次：思考文本 + 轮次时间线 + 最终答案（只消费投影，不解释原始事件） */
function LiveAssistantRow({ item, onInspectTool }: { item: LiveAssistantItem; onInspectTool: (tool: ToolStepView) => void }) {
  const turn = item.projection.turn;
  const streaming = turn.runStatus === "streaming";
  const text = selectVisibleText(turn);
  return (
    <AssistantShell>
      <AssistantTurn turn={turn} current onInspectTool={onInspectTool}>
        {text ? (
          <div className="max-w-[68ch]">
            <MarkdownView content={text} />
            {streaming ? (
              <span className="mt-1 inline-block h-3.5 w-1 animate-pulse rounded-sm bg-primary/70" />
            ) : null}
          </div>
        ) : null}
      </AssistantTurn>
    </AssistantShell>
  );
}

/** 无会话时的欢迎空态：模式 chips 为提示策略前缀（§10），示例问题为完整提问。 */
function Welcome({ onPick, onPickMode }: { onPick: (q: string) => void; onPickMode: (prefix: string) => void }) {
  return (
    <div className="flex h-full items-center justify-center">
      <EmptyState
        icon={Sparkles}
        title="开始新的学习对话"
        description="向 AI 助教提问任意学习问题，支持工具调用与思考过程展示。"
        className="w-full max-w-lg"
        action={
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-center gap-2">
              {COMPOSER_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => onPickMode(m.prefix)}
                  className="rounded-full border border-spectral/30 bg-accent px-3 py-1.5 text-xs font-medium text-accent-foreground shadow-soft transition-colors hover:bg-accent/70"
                >
                  {m.label}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center justify-center gap-2">
              {EXAMPLE_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => onPick(q)}
                  className="rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-soft transition-colors hover:bg-accent hover:text-accent-foreground"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        }
      />
    </div>
  );
}

/** 会话列表面板：宽屏为固定左栏，小屏（<1024px）经 Sheet 复用（§5.2：会话历史为 Sheet）。 */
function ConversationListPanel({
  conversations,
  isPending,
  convId,
  creating,
  onNew,
  onOpen,
  onRename,
  onDelete,
}: {
  conversations: Conversation[];
  isPending: boolean;
  convId: number | null;
  creating: boolean;
  onNew: () => void;
  onOpen: (id: number) => void;
  onRename: (c: Conversation) => void;
  onDelete: (c: Conversation) => void;
}) {
  return (
    <>
      <div className="border-b border-border p-3">
        <Button className="w-full" onClick={onNew} disabled={creating}>
          {creating ? <Spinner className="text-primary-foreground" /> : <Plus />}
          新建对话
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isPending ? (
          <div className="space-y-2 p-1">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        ) : conversations.length === 0 ? (
          <div className="px-2 py-8 text-center text-xs text-muted-foreground">
            还没有对话，点击上方按钮开始
          </div>
        ) : (
          <ul className="space-y-1">
            {conversations.map((c) => (
              <li key={c.id}>
                <div
                  className={cn(
                    "group flex items-start gap-1 rounded-md px-2 py-2 transition-colors",
                    c.id === convId ? "bg-accent text-accent-foreground" : "hover:bg-muted",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => onOpen(c.id)}
                    className="min-w-0 flex-1 text-left"
                  >
                    <div className="truncate text-sm font-medium">{c.title || "未命名对话"}</div>
                    <div className="mt-0.5 text-xs text-muted-foreground">{formatRelative(c.updated_at)}</div>
                  </button>
                  <div className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                    <button
                      type="button"
                      title="重命名"
                      onClick={() => onRename(c)}
                      className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                    >
                      <Pencil className="size-3.5" />
                    </button>
                    <button
                      type="button"
                      title="删除"
                      onClick={() => onDelete(c)}
                      className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-background hover:text-destructive"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

// ---------------- 页面 ----------------

export function ChatPage() {
  const navigate = useNavigate();
  const params = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);

  const parsed = params.id ? Number(params.id) : NaN;
  const convId = Number.isInteger(parsed) && parsed > 0 ? parsed : null;

  const [input, setInput] = useState("");
  const [subject, setSubject] = useState<string | undefined>(undefined);
  const [sending, setSending] = useState(false);
  const [live, setLive] = useState<LiveItem[]>([]);
  const [renameTarget, setRenameTarget] = useState<Conversation | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  /** 全局搜索携带 ?message= 锚点：历史加载后滚动并短暂高亮该条消息 */
  const [searchParams] = useSearchParams();
  const targetMessageId = searchParams.get("message") ? Number(searchParams.get("message")) : null;
  const [highlightMsgId, setHighlightMsgId] = useState<number | null>(null);
  /** 小屏会话列表 Sheet（<1024px 时左栏隐藏） */
  const [convListOpen, setConvListOpen] = useState(false);
  /** 工具检查器：选中的工具 + 打开时的轮次快照（流式期间随投影刷新，落库后保留快照） */
  const [inspector, setInspector] = useState<{ toolId: string; turn: ConversationTurnView } | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const streamConvRef = useRef<number | null>(null);
  const projectionRef = useRef<Map<string, ChatProjectionState>>(new Map());
  const scrollRef = useRef<HTMLDivElement>(null);
  /** 取消已被服务端接受后的兜底计时器：超时未收到 cancelled 确认则本地中止接收。 */
  const cancelTimerRef = useRef<number | null>(null);

  const conversationsQuery = useQuery({
    queryKey: ["conversations"],
    queryFn: () => conversationsApi.list(),
  });

  const messagesQuery = useQuery({
    queryKey: ["messages", convId],
    // include_trace：拉取工具调用历史（tool 消息内容留空，仅展示记录与成败）
    queryFn: () => conversationsApi.messages(convId as number, { includeTrace: true }),
    enabled: convId != null,
  });

  const createMutation = useMutation({
    mutationFn: (title?: string) => conversationsApi.create(title),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      navigate(`/chat/${created.id}`);
    },
    onError: (err) => toast({ title: "新建对话失败", description: errorText(err), variant: "destructive" }),
  });

  const renameMutation = useMutation({
    mutationFn: (vars: { id: number; title: string }) => conversationsApi.rename(vars.id, vars.title),
    onSuccess: () => {
      toast({ title: "已重命名", variant: "success" });
      setRenameTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err) => toast({ title: "重命名失败", description: errorText(err), variant: "destructive" }),
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => conversationsApi.remove(id),
    onSuccess: (_data, id) => {
      toast({ title: "对话已删除", variant: "success" });
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (id === convId) navigate("/chat");
    },
    onError: (err) => toast({ title: "删除失败", description: errorText(err), variant: "destructive" }),
  });

  // 切换到其他会话时，中止仍在进行的流并丢弃本地流式消息
  useEffect(() => {
    if (streamConvRef.current != null && streamConvRef.current !== convId) {
      abortRef.current?.abort();
      abortRef.current = null;
      streamConvRef.current = null;
      projectionRef.current.clear();
      setSending(false);
      setLive([]);
    }
  }, [convId]);

  // 会话切换后关闭检查器（轮次上下文已不存在）
  useEffect(() => {
    setInspector(null);
  }, [convId]);

  // 卸载时中止流（流只能由用户动作触发，这里只做清理）
  useEffect(
    () => () => {
      abortRef.current?.abort();
      if (cancelTimerRef.current != null) window.clearTimeout(cancelTimerRef.current);
    },
    [],
  );

  // 检查器打开期间，轮次快照随流式投影刷新；live 清空（正常落库）后保留最后快照
  useEffect(() => {
    setInspector((prev) => {
      if (!prev) return prev;
      const item = live.find((m): m is LiveAssistantItem => m.role === "assistant");
      if (!item) return prev;
      if (item.projection.turn === prev.turn) return prev;
      return { ...prev, turn: item.projection.turn };
    });
  }, [live]);

  const history = useMemo(() => messagesQuery.data?.messages ?? [], [messagesQuery.data]);

  // 新建会话后立即发流：历史里可能已落库刚发送的用户消息，避免与本地消息重复渲染
  const displayHistory = useMemo(() => {
    const liveUser = live.find((m): m is LiveUserItem => m.role === "user");
    if (!liveUser || history.length === 0) return history;
    const last = history[history.length - 1];
    if (last.role === "user" && last.content === liveUser.content) return history.slice(0, -1);
    return history;
  }, [history, live]);

  // 语义确认（§9.1）：最后一条 assistant 消息提出 <EXAM_PAPER_PLAN> 方案且当前无生成时显示快捷操作
  const planProposed = useMemo(() => {
    if (sending || live.length > 0) return false;
    for (let i = displayHistory.length - 1; i >= 0; i--) {
      const m = displayHistory[i];
      if (m.role !== "assistant" || !m.content) continue;
      return m.content.includes("<EXAM_PAPER_PLAN>");
    }
    return false;
  }, [displayHistory, sending, live]);

  // 新内容到达时，仅当用户停留在底部附近才跟随滚动；否则显示「回到最新」
  useEffect(() => {
    const el = scrollRef.current;
    if (el && pinnedToBottom) el.scrollTop = el.scrollHeight;
  }, [displayHistory.length, live, pinnedToBottom]);

  // 全局搜索携带 ?message= 锚点进入：历史加载完成后滚动并短暂高亮该条消息
  useEffect(() => {
    if (targetMessageId == null || !Number.isInteger(targetMessageId) || displayHistory.length === 0) return;
    const el = document.querySelector(`[data-message-id="${targetMessageId}"]`);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    setHighlightMsgId(targetMessageId);
    const t = window.setTimeout(() => setHighlightMsgId(null), 2200);
    return () => window.clearTimeout(t);
  }, [targetMessageId, displayHistory.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    setPinnedToBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80);
  };

  const scrollToLatest = () => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setPinnedToBottom(true);
  };

  /** 纯函数投影更新：ref 同步保存最新状态（供 settle 决策同步读取），state 驱动渲染。 */
  const dispatchProjection = (key: string, action: ChatProjectionAction): ChatProjectionState => {
    const prev = projectionRef.current.get(key) ?? initialChatProjection();
    const next = chatProjectionReducer(prev, action);
    projectionRef.current.set(key, next);
    setLive((prevLive) =>
      prevLive.map((m) => (m.key === key && m.role === "assistant" ? { ...m, projection: next } : m)),
    );
    return next;
  };

  /** 生成中离开当前会话需要确认：中止接收不代表服务端工具停止。 */
  const confirmLeaveStream = (): boolean => {
    if (!sending) return true;
    return window.confirm("离开将停止接收当前生成；服务端工具可能仍会执行。确定离开吗？");
  };

  /**
   * 停止：优先走服务端取消契约（POST /api/chat/{id}/cancel），等待流内 cancelled
   * 确认后按「任务已停止」呈现；取消不可达/未被接受/超时时回退本地「停止接收」。
   */
  const stopReceiving = () => {
    const key = live.find((m): m is LiveAssistantItem => m.role === "assistant")?.key;
    if (key) {
      dispatchProjection(key, { type: "stop_requested", at: Date.now() });
    }
    const convForCancel = streamConvRef.current;
    if (convForCancel == null) {
      abortRef.current?.abort();
      return;
    }
    void conversationsApi
      .cancelGeneration(convForCancel)
      .then((res) => {
        if (!res.accepted) {
          abortRef.current?.abort();
          return;
        }
        if (cancelTimerRef.current != null) window.clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = window.setTimeout(() => abortRef.current?.abort(), 8000);
      })
      .catch(() => abortRef.current?.abort());
  };

  /** 「查看详情」：打开检查器（不自动抢焦点，仅在用户点击后展开）。 */
  const openInspector = (tool: ToolStepView) => {
    const item = live.find((m): m is LiveAssistantItem => m.role === "assistant");
    if (!item) return;
    setInspector({ toolId: tool.id, turn: item.projection.turn });
  };

  const send = async (messageOverride?: string, opts?: { intent?: string }) => {
    const message = (messageOverride ?? input).trim();
    if (!message || sending) return;
    setInput("");
    setInspector(null);

    let targetConv = convId;
    if (targetConv == null) {
      try {
        const created = await conversationsApi.create(message.slice(0, 20));
        targetConv = created.id;
        navigate(`/chat/${created.id}`, { replace: true });
        void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      } catch (err) {
        toast({ title: "创建对话失败", description: errorText(err), variant: "destructive" });
        return;
      }
    }
    const convIdForStream = targetConv;

    const controller = new AbortController();
    abortRef.current = controller;
    streamConvRef.current = convIdForStream;
    setSending(true);
    setPinnedToBottom(true);

    const userKey = `live-user-${Date.now()}`;
    const asstKey = `live-asst-${Date.now()}`;
    projectionRef.current.set(asstKey, initialChatProjection());
    setLive([
      { key: userKey, role: "user", content: message },
      { key: asstKey, role: "assistant", projection: initialChatProjection() },
    ]);

    const finishStream = (reason: StreamEndReason, projection: ChatProjectionState) => {
      setSending(false);
      abortRef.current = null;
      streamConvRef.current = null;
      if (cancelTimerRef.current != null) {
        window.clearTimeout(cancelTimerRef.current);
        cancelTimerRef.current = null;
      }
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });

      if (reason === "completed" && (projection.seenFinal || projection.seenCancelled)) {
        // 正常完成 / 服务端确认取消：以落库数据为准刷新历史，完成后丢弃本地流式消息
        void (async () => {
          await queryClient.invalidateQueries({ queryKey: ["messages", convIdForStream] });
          projectionRef.current.delete(asstKey);
          setLive([]);
        })();
        return;
      }
      if (reason === "error") {
        // 传输层失败：保留本地轮次展示错误；刷新历史（用户消息已落库，依赖去重）
        void queryClient.invalidateQueries({ queryKey: ["messages", convIdForStream] });
        return;
      }
      // aborted / eof / 无 final 的 completed：保留已收到内容并标记 interrupted（本轮会话内可见）。
      // 不刷新消息历史：服务端可能仍在执行，落库内容以用户下次进入/刷新为准。
    };

    await sendChatMessage(
      {
        conversation_id: convIdForStream,
        message,
        ...(subject ? { subject } : {}),
        ...(opts?.intent ? { intent: opts.intent } : {}),
      },
      {
        signal: controller.signal,
        onEvent: (ev) => {
          const decoded = decodeChatEvent(ev);
          if (!decoded) return;
          dispatchProjection(asstKey, { type: "event", event: decoded, at: Date.now() });
        },
        onError: (err) => {
          const desc = err instanceof ApiError ? err.message : "网络连接失败，请检查后端服务";
          toast({ title: "发送失败", description: desc, variant: "destructive" });
        },
        onSettled: (termination) => {
          const projection = dispatchProjection(asstKey, {
            type: "settled",
            reason: termination.reason,
            at: Date.now(),
            ...(termination.reason === "error" ? { error: termination.error } : {}),
          });
          finishStream(termination.reason, projection);
        },
      },
    );
  };

  // 首页 Intent Workspace 带入的消息：进入空会话时自动发送一次（ref 防 StrictMode 重复）
  const location = useLocation();
  const intentHandledRef = useRef(false);
  useEffect(() => {
    const intent = (location.state as { intentMessage?: string } | null)?.intentMessage;
    if (!intent || intentHandledRef.current || convId != null) return;
    intentHandledRef.current = true;
    setInput(intent);
    void send(intent);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state, convId]);

  const conversations = conversationsQuery.data ?? [];
  const currentTitle =
    messagesQuery.data?.conversation.title ?? conversations.find((c) => c.id === convId)?.title ?? "对话";

  return (
    <div className="flex h-full min-h-0 animate-fade-in gap-4 p-4">
      {/* 左栏：会话列表（≥1024px 固定；小屏经顶部按钮以 Sheet 打开） */}
      <aside className="hidden w-60 shrink-0 flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-soft lg:flex">
        <ConversationListPanel
          conversations={conversations}
          isPending={conversationsQuery.isPending}
          convId={convId}
          creating={createMutation.isPending}
          onNew={() => {
            if (confirmLeaveStream()) createMutation.mutate(undefined);
          }}
          onOpen={(id) => {
            if (id !== convId && confirmLeaveStream()) navigate(`/chat/${id}`);
          }}
          onRename={(c) => {
            setRenameTarget(c);
            setRenameValue(c.title);
          }}
          onDelete={setDeleteTarget}
        />
      </aside>

      {/* 右栏：消息线程 + 输入区（检查器附着时作为同层右列） */}
      <section className="flex min-w-0 flex-1 overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-4">
            <Button
              variant="ghost"
              size="icon-sm"
              className="lg:hidden"
              onClick={() => setConvListOpen(true)}
              aria-label="会话列表"
            >
              <List />
            </Button>
            <MessagesSquare className="size-4 text-muted-foreground" />
            <div className="truncate text-sm font-medium">{convId != null ? currentTitle : "新对话"}</div>
          </div>

          <div className="relative min-h-0 flex-1">
            <div ref={scrollRef} onScroll={handleScroll} className="h-full overflow-y-auto px-4 py-4">
              <div className="mx-auto max-w-[800px]">
                {convId == null ? (
                  <Welcome onPick={(q) => setInput(q)} onPickMode={(prefix) => setInput(prefix)} />
                ) : messagesQuery.isPending ? (
                  <div className="space-y-4">
                    <div className="flex justify-end">
                      <Skeleton className="h-10 w-1/3" />
                    </div>
                    <div className="flex items-start gap-2.5">
                      <Skeleton className="size-7 shrink-0 rounded-full" />
                      <Skeleton className="h-24 w-2/3" />
                    </div>
                    <div className="flex justify-end">
                      <Skeleton className="h-10 w-1/4" />
                    </div>
                  </div>
                ) : messagesQuery.isError ? (
                  <Alert variant="destructive">
                    <AlertDescription>{errorText(messagesQuery.error)}</AlertDescription>
                  </Alert>
                ) : (
                  <div className="space-y-5">
                    {displayHistory.length === 0 && live.length === 0 ? (
                      <div className="py-10 text-center text-sm text-muted-foreground">
                        暂无消息，在下方输入问题开始对话
                      </div>
                    ) : null}
                    {displayHistory.map((m) => (
                      <HistoryRow key={m.id} message={m} highlight={m.id === highlightMsgId} />
                    ))}
                    {live.map((m) =>
                      m.role === "user" ? (
                        <UserBubble key={m.key} content={m.content} />
                      ) : (
                        <LiveAssistantRow key={m.key} item={m} onInspectTool={openInspector} />
                      ),
                    )}
                  </div>
                )}
              </div>
            </div>
            {!pinnedToBottom ? (
              <button
                type="button"
                onClick={scrollToLatest}
                className="absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-surface-raised px-3 py-1.5 text-xs text-muted-foreground shadow-lift transition-colors hover:text-foreground"
              >
                <ArrowDown className="size-3.5" />
                回到最新
              </button>
            ) : null}
          </div>

          <div className="shrink-0 px-3 pb-3">
            <div className="mx-auto max-w-[880px]">
              {planProposed ? (
                <SemanticConfirmation
                  onConfirm={() => void send("确认，请按当前方案创建试卷。", { intent: "confirm_create_paper" })}
                  onRevise={() => setInput("我想调整方案：")}
                  onViewCandidates={() =>
                    void send("请先展示方案中各题槽的候选题目，暂不创建试卷。", { intent: "view_candidates" })
                  }
                />
              ) : null}
              <PromptComposer
                value={input}
                onChange={setInput}
                onSubmit={() => void send()}
                sending={sending}
                onStop={stopReceiving}
                stopLabel="停止任务"
                stopTitle="请求服务端停止本轮生成；确认前保留已接收内容"
                autoFocus
                leftSlot={
                  <>
                    <SubjectSelect
                      value={subject ?? ""}
                      onValueChange={(v) => setSubject(v || undefined)}
                      placeholder="不指定学科"
                      className="w-36"
                    />
                    {subject ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        title="清除学科（不指定）"
                        onClick={() => setSubject(undefined)}
                      >
                        <X />
                      </Button>
                    ) : null}
                  </>
                }
              />
            </div>
          </div>
        </div>

        {inspector ? (
          <ToolInspectorHost
            turn={inspector.turn}
            selectedToolId={inspector.toolId}
            onSelectTool={(toolId) => setInspector((prev) => (prev ? { ...prev, toolId } : prev))}
            onClose={() => setInspector(null)}
          />
        ) : null}
      </section>

      {/* 小屏会话列表 Sheet */}
      <Sheet open={convListOpen} onOpenChange={setConvListOpen}>
        <SheetContent side="left" className="flex w-80 p-0" aria-label="会话列表">
          <SheetHeader className="sr-only">
            <SheetTitle>会话列表</SheetTitle>
            <SheetDescription>选择、新建或管理对话</SheetDescription>
          </SheetHeader>
          <ConversationListPanel
            conversations={conversations}
            isPending={conversationsQuery.isPending}
            convId={convId}
            creating={createMutation.isPending}
            onNew={() => {
              setConvListOpen(false);
              if (confirmLeaveStream()) createMutation.mutate(undefined);
            }}
            onOpen={(id) => {
              setConvListOpen(false);
              if (id !== convId && confirmLeaveStream()) navigate(`/chat/${id}`);
            }}
            onRename={(c) => {
              setConvListOpen(false);
              setRenameTarget(c);
              setRenameValue(c.title);
            }}
            onDelete={(c) => {
              setConvListOpen(false);
              setDeleteTarget(c);
            }}
          />
        </SheetContent>
      </Sheet>

      {/* 重命名对话框 */}
      <Dialog
        open={renameTarget != null}
        onOpenChange={(open) => {
          if (!open) setRenameTarget(null);
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>重命名对话</DialogTitle>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              const title = renameValue.trim();
              if (!renameTarget || !title) return;
              renameMutation.mutate({ id: renameTarget.id, title });
            }}
          >
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              maxLength={60}
              placeholder="输入新的对话标题"
              autoFocus
            />
            <DialogFooter>
              <Button type="button" variant="ghost" onClick={() => setRenameTarget(null)}>
                取消
              </Button>
              <Button type="submit" disabled={renameMutation.isPending || !renameValue.trim()}>
                {renameMutation.isPending ? <Spinner className="text-primary-foreground" /> : null}
                保存
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog
        open={deleteTarget != null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>删除对话</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            确定要删除「{deleteTarget?.title || "未命名对话"}」吗？该操作不可恢复。
          </p>
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={removeMutation.isPending}
              onClick={() => deleteTarget && removeMutation.mutate(deleteTarget.id)}
            >
              {removeMutation.isPending ? <Spinner /> : null}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
