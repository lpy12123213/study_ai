import { memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { format } from "date-fns";
import { useQueryClient } from "@tanstack/react-query";
import {
  Background,
  BackgroundVariant,
  Controls,
  Panel,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  Handle,
  Position,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Bot,
  ChevronLeft,
  ChevronRight,
  GitFork,
  MessagesSquare,
  Plus,
  Search,
  Send,
  Settings2,
  Square,
  Trash2,
  User,
  Wrench,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useConversations, useConversationMessages, useCreateConversation, useDeleteConversation, useForkConversation, useUpdateConversationTitle } from "@/hooks/useChat";
import { useSubjects } from "@/hooks/useSubjects";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { apiUrl } from "@/lib/apiUrl";
import { readSseData } from "@/lib/sse";
import { cn } from "@/lib/utils";
import type { Message, Subject } from "@/types";

type FlowMessageNodeData = {
  role: Message["role"];
  content: string;
  created_at?: string;
  isStreaming?: boolean;
  messageId?: number;
  onFork?: (messageId: number) => void;
};

type FlowMessageNode = Node<FlowMessageNodeData, "message">;

function titleFromPrompt(prompt: string): string {
  const trimmed = prompt.trim();
  if (!trimmed) return "新对话";
  return trimmed.length > 30 ? `${trimmed.slice(0, 30)}...` : trimmed;
}

function formatTime(iso?: string): string {
  if (!iso) return "";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  return format(dt, "HH:mm");
}

function FlowMessageNodeView({ data, selected }: NodeProps<FlowMessageNode>) {
  const isUser = data.role === "user";
  const isTool = data.role === "tool";
  const Icon = isTool ? Wrench : isUser ? User : Bot;

  const canFork = Boolean(data.onFork && data.messageId && !isTool);

  return (
    <div
      className={cn(
        "relative min-w-[260px] max-w-[440px] rounded-xl border shadow-md transition-all",
        isTool
          ? "bg-muted/40 text-foreground border-border"
          : isUser
            ? "bg-primary text-primary-foreground border-primary/50"
            : "bg-card text-card-foreground border-border",
        selected && "ring-2 ring-ring ring-offset-2 ring-offset-background",
      )}
    >
      <div className="flex items-center gap-2 px-4 py-2 border-b border-inherit/20">
        <Icon className="h-4 w-4" />
        <span className="text-xs font-medium">
          {isTool ? "Tool" : isUser ? "Student" : "AI"}
        </span>
        {data.created_at ? (
          <span className="text-[10px] opacity-70 tabular-nums">
            {formatTime(data.created_at)}
          </span>
        ) : null}
        {canFork ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="ml-auto h-7 w-7 opacity-70 hover:opacity-100"
            onClick={() => data.onFork?.(data.messageId!)}
            title="从这里分叉对话"
          >
            <GitFork className="h-3.5 w-3.5" />
          </Button>
        ) : null}
      </div>

      <div className={cn("px-4 py-3 text-sm whitespace-pre-wrap", isTool && "font-mono text-xs")}>
        {data.content}
        {data.isStreaming ? (
          <span className="ml-1.5 inline-block h-3 w-1.5 animate-pulse bg-current/60 rounded-full align-middle" />
        ) : null}
      </div>

      <Handle type="target" position={Position.Top} className="!bg-muted-foreground !w-3 !h-3" />
      <Handle type="source" position={Position.Bottom} className="!bg-muted-foreground !w-3 !h-3" />
    </div>
  );
}

const MemoFlowMessageNodeView = memo(FlowMessageNodeView);

function asConversationId(raw: string | undefined): number | null {
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function nextCanvasY(nodes: Array<{ position: { y: number } }>, fallback: number): number {
  if (!nodes.length) return fallback;
  let maxY = fallback;
  for (const n of nodes) {
    if (typeof n.position?.y === "number") {
      maxY = Math.max(maxY, n.position.y);
    }
  }
  return maxY + 200;
}

function buildGraphFromMessages(args: {
  messages: Message[];
  showTools: boolean;
  onFork?: (messageId: number) => void;
}): { nodes: FlowMessageNode[]; edges: Edge[] } {
  const { messages, showTools, onFork } = args;
  const visible = showTools ? messages : messages.filter((m) => m.role !== "tool");

  const nodes: FlowMessageNode[] = [];
  const edges: Edge[] = [];

  const startY = 40;
  const gapY = 200;

  for (let idx = 0; idx < visible.length; idx += 1) {
    const m = visible[idx];
    const id = `msg-${m.id}`;

    const role = m.role;
    const x = role === "user" ? 420 : role === "assistant" ? 0 : 210;
    const y = startY + idx * gapY;

    nodes.push({
      id,
      type: "message",
      position: { x, y },
      data: {
        role,
        content: m.content || "",
        created_at: m.created_at,
        messageId: m.id,
        onFork,
      },
    });

    if (idx === 0) continue;
    const prev = visible[idx - 1];
    edges.push({
      id: `edge-msg-${prev.id}-msg-${m.id}`,
      source: `msg-${prev.id}`,
      target: id,
      animated: false,
      style: { stroke: "hsl(var(--muted-foreground) / 0.55)" },
    });
  }

  return { nodes, edges };
}

export default function FlowChatPage() {
  const params = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const conversationId = useMemo(
    () => asConversationId(params.conversationId),
    [params.conversationId],
  );

  const conversationsQuery = useConversations();
  const messagesQuery = useConversationMessages(conversationId);
  const createConversation = useCreateConversation();
  const deleteConversation = useDeleteConversation();
  const updateConversationTitle = useUpdateConversationTitle();
  const forkConversation = useForkConversation();

  const subjectsQuery = useSubjects();
  const subjects = useMemo(() => subjectsQuery.data ?? [], [subjectsQuery.data]);

  const [subjectName, setSubjectName] = useLocalStorageState<string>(
    "epa_subject_name",
    "高中数学",
  );
  const [showTools, setShowTools] = useLocalStorageState<boolean>(
    "epa_show_tool_messages",
    false,
  );
  const [modelOverride, setModelOverride] = useLocalStorageState<string>(
    "epa_model_override",
    "",
  );
  const [subModelOverride, setSubModelOverride] = useLocalStorageState<string>(
    "epa_sub_model_override",
    "",
  );

  const [leftPanelCollapsed, setLeftPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_flow_left_panel_collapsed",
    false,
  );
  const [rightPanelCollapsed, setRightPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_flow_right_panel_collapsed",
    false,
  );

  const [conversationFilter, setConversationFilter] = useState("");
  const [draft, setDraft] = useState("");
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const hasLocalEditsRef = useRef(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<FlowMessageNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const nodeTypes = useMemo(() => ({ message: MemoFlowMessageNodeView }), []);

  const subjectOptions = useMemo(() => {
    const grouped = new Map<number, Subject[]>();
    for (const s of subjects) {
      grouped.set(s.edu_id, [...(grouped.get(s.edu_id) ?? []), s]);
    }
    return Array.from(grouped.entries()).sort(([a], [b]) => a - b);
  }, [subjects]);

  useEffect(() => {
    if (!subjects.length) return;
    if (subjects.some((s) => s.name === subjectName)) return;
    setSubjectName(subjects[0]?.name ?? "高中数学");
  }, [subjects, subjectName, setSubjectName]);

  const filteredConversations = useMemo(() => {
    const list = conversationsQuery.data ?? [];
    const q = conversationFilter.trim().toLowerCase();
    if (!q) return list;
    return list.filter((c) => (c.title || "").toLowerCase().includes(q));
  }, [conversationsQuery.data, conversationFilter]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge(params, eds)),
    [setEdges],
  );

  const stopStreaming = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
  };

  const handleForkFromMessage = useCallback(
    async (messageId: number) => {
      if (!conversationId) return;
      const parent = conversationsQuery.data?.find((c) => c.id === conversationId) ?? null;
      const title = `${parent?.title || `对话 #${conversationId}`} - 分支`;
      const created = await forkConversation.mutateAsync({ id: conversationId, messageId, title });
      navigate(`/flow/${created.id}`);
    },
    [conversationId, conversationsQuery.data, forkConversation, navigate],
  );

  useEffect(() => {
    if (!conversationId) {
      hasLocalEditsRef.current = false;
      setNodes([]);
      setEdges([]);
      setStreamError(null);
      setIsStreaming(false);
      abortRef.current?.abort();
      abortRef.current = null;
      return;
    }

    if (!messagesQuery.data?.messages) return;
    if (isStreaming || hasLocalEditsRef.current) return;

    const { nodes: nextNodes, edges: nextEdges } = buildGraphFromMessages({
      messages: messagesQuery.data.messages,
      showTools,
      onFork: handleForkFromMessage,
    });

    setNodes((prev) => {
      const prevPos = new Map(prev.map((n) => [n.id, n.position]));
      return nextNodes.map((n) =>
        prevPos.has(n.id) ? { ...n, position: prevPos.get(n.id)! } : n,
      );
    });
    setEdges(nextEdges);
  }, [conversationId, messagesQuery.data?.messages, showTools, isStreaming, setEdges, setNodes, handleForkFromMessage]);

  const handleNewConversation = async () => {
    const created = await createConversation.mutateAsync("新对话");
    navigate(`/flow/${created.id}`);
  };

  const handleDeleteConversation = async (id: number) => {
    const ok = window.confirm("确定要删除这个对话吗？该操作不可撤销。");
    if (!ok) return;
    await deleteConversation.mutateAsync(id);
    if (conversationId === id) {
      navigate("/flow");
    }
  };

  const handleRenameConversation = async (id: number, currentTitle: string) => {
    const next = window.prompt("请输入新的对话标题：", currentTitle || "");
    const title = (next ?? "").trim();
    if (!title) return;
    await updateConversationTitle.mutateAsync({ id, title });
  };

  const handleSend = async () => {
    const prompt = draft.trim();
    if (!prompt || isStreaming) return;

    setDraft("");
    setStreamError(null);
    hasLocalEditsRef.current = true;

    let convId = conversationId;
    if (!convId) {
      const created = await createConversation.mutateAsync(titleFromPrompt(prompt));
      convId = created.id;
      navigate(`/flow/${created.id}`, { replace: true });
      setNodes([]);
      setEdges([]);
    }

    const nowIso = new Date().toISOString();
    const localUserId = `local-user-${crypto.randomUUID()}`;
    const localAssistantId = `local-assistant-${crypto.randomUUID()}`;

    const y = nextCanvasY(nodes, 40);

    const userNode: FlowMessageNode = {
      id: localUserId,
      type: "message",
      position: { x: 420, y },
      data: {
        role: "user",
        content: prompt,
        created_at: nowIso,
      },
    };
    const assistantNode: FlowMessageNode = {
      id: localAssistantId,
      type: "message",
      position: { x: 0, y: y + 200 },
      data: {
        role: "assistant",
        content: "",
        created_at: nowIso,
        isStreaming: true,
      },
    };

    const lastNodeId = nodes.length ? nodes[nodes.length - 1].id : undefined;
    const newEdges: Edge[] = [];
    if (lastNodeId) {
      newEdges.push({
        id: `edge-${lastNodeId}-${localUserId}`,
        source: lastNodeId,
        target: localUserId,
        animated: false,
        style: { stroke: "hsl(var(--muted-foreground) / 0.55)" },
      });
    }
    newEdges.push({
      id: `edge-${localUserId}-${localAssistantId}`,
      source: localUserId,
      target: localAssistantId,
      animated: true,
      style: { stroke: "hsl(var(--primary) / 0.55)" },
    });

    setNodes((prev) => [...prev, userNode, assistantNode]);
    setEdges((prev) => [...prev, ...newEdges]);

    setIsStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    let assistantText = "";

    try {
      const res = await fetch(apiUrl("chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify({
          conversation_id: convId,
          message: prompt,
          subject: subjectName,
          model: modelOverride.trim() || undefined,
          sub_model: subModelOverride.trim() || undefined,
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }

      for await (const data of readSseData(res, { signal: controller.signal })) {
        if (data === "[DONE]") break;

        let evt: Record<string, unknown>;
        try {
          evt = JSON.parse(data) as Record<string, unknown>;
        } catch {
          continue;
        }

        if (evt.type === "text_delta") {
          const delta = typeof evt.content === "string" ? evt.content : "";
          assistantText += delta;
          setNodes((prev) =>
            prev.map((n) =>
              n.id === localAssistantId
                ? {
                    ...n,
                    data: { ...n.data, content: assistantText, isStreaming: true },
                  }
                : n,
            ),
          );
          continue;
        }

        if (evt.type === "assistant_final") {
          const finalText = typeof evt.content === "string" ? evt.content : assistantText;
          assistantText = finalText;
          setNodes((prev) =>
            prev.map((n) =>
              n.id === localAssistantId
                ? {
                    ...n,
                    data: { ...n.data, content: finalText, isStreaming: false },
                  }
                : n,
            ),
          );
          continue;
        }

        if (evt.type === "error") {
          const message = typeof evt.message === "string" ? evt.message : "未知错误";
          setStreamError(message);
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setStreamError("已停止生成。");
      } else {
        setStreamError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      abortRef.current = null;
      setIsStreaming(false);
      setNodes((prev) =>
        prev.map((n) =>
          n.id === localAssistantId ? { ...n, data: { ...n.data, isStreaming: false } } : n,
        ),
      );
      hasLocalEditsRef.current = false;

      // Ensure we get canonical message IDs and enable forking.
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (convId) {
        queryClient.invalidateQueries({ queryKey: ["conversations", convId, "messages"] });
      }
    }
  };

  const chatTitle =
    messagesQuery.data?.conversation?.title ||
    (conversationId ? `对话 #${conversationId}` : "画布对话");

  return (
    <div className="flex h-full bg-background overflow-hidden">
      {/* Conversations */}
      <aside
        className={cn(
          "shrink-0 border-r bg-muted/10 flex flex-col overflow-hidden transition-[width] duration-200 ease-in-out",
          leftPanelCollapsed ? "w-14" : "w-[300px]",
        )}
      >
        {leftPanelCollapsed ? (
          <div className="h-full flex flex-col items-center gap-2 p-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => setLeftPanelCollapsed(false)}
              title="展开左侧面板"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
            <div className="h-px w-7 bg-border my-1" />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => void handleNewConversation()}
              title="新建对话"
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <>
            <div className="p-4 border-b space-y-3 bg-background/50 backdrop-blur-sm">
              <div className="flex items-center justify-between gap-2">
                <Button onClick={() => void handleNewConversation()} className="flex-1 gap-2 shadow-sm">
                  <Plus className="h-4 w-4" />
                  新建对话
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => setLeftPanelCollapsed(true)}
                  title="折叠左侧面板"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
              </div>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  value={conversationFilter}
                  onChange={(e) => setConversationFilter(e.target.value)}
                  placeholder="搜索历史..."
                  className="pl-9 h-9"
                />
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-2">
              {conversationsQuery.isLoading ? (
                <div className="p-4 text-center text-sm text-muted-foreground animate-pulse">加载列表...</div>
              ) : filteredConversations.length === 0 ? (
                <div className="p-8 text-center text-sm text-muted-foreground">
                  <div className="mx-auto mb-3 h-10 w-10 rounded-full bg-muted flex items-center justify-center">
                    <MessagesSquare className="h-5 w-5 opacity-50" />
                  </div>
                  暂无历史记录
                </div>
              ) : (
                <div className="space-y-1">
                  {filteredConversations.map((c) => {
                    const active = conversationId === c.id;
                    return (
                      <div
                        key={c.id}
                        className={cn(
                          "group relative flex items-center rounded-lg px-3 py-2.5 transition-all duration-200 cursor-pointer",
                          active ? "bg-primary/10 text-primary" : "hover:bg-muted/50 text-foreground",
                        )}
                        onClick={() => navigate(`/flow/${c.id}`)}
                      >
                        <div className="min-w-0 flex-1">
                          <div className={cn("truncate text-sm font-medium", active && "font-semibold")}>
                            {c.title || `对话 #${c.id}`}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-[10px] text-muted-foreground/80 font-mono">
                              {formatTime(c.updated_at)}
                            </span>
                          </div>
                        </div>

                        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleRenameConversation(c.id, c.title);
                            }}
                            title="重命名"
                          >
                            <Settings2 className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                            onClick={(e) => {
                              e.stopPropagation();
                              void handleDeleteConversation(c.id);
                            }}
                            title="删除"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}
      </aside>

      {/* Graph */}
      <section className="flex-1 min-w-0 relative">
        <div className="h-14 border-b flex items-center justify-between px-4 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <div className="min-w-0">
            <div className="font-semibold truncate">{chatTitle}</div>
            <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
              <Badge variant="secondary" className="h-5 px-1.5 font-normal">
                {subjectName}
              </Badge>
              {modelOverride ? (
                <Badge variant="outline" className="h-5 px-1.5 font-normal">
                  {modelOverride}
                </Badge>
              ) : null}
            </div>
          </div>

          {isStreaming ? (
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={stopStreaming}
              className="h-8 gap-1.5 shadow-sm"
            >
              <Square className="h-3 w-3 fill-current" />
              停止
            </Button>
          ) : null}
        </div>

        <div className="absolute inset-x-0 bottom-0 top-14">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            nodeTypes={nodeTypes}
            fitView
            proOptions={{ hideAttribution: true }}
            className="bg-muted/20"
          >
            <Controls />
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />

            <Panel position="bottom-center" className="w-full max-w-3xl mb-4">
              <div className="rounded-2xl border bg-background/80 backdrop-blur shadow-sm p-3">
                {streamError ? (
                  <div className="mb-2 rounded-lg border border-destructive/50 bg-destructive/5 p-2 text-xs text-destructive text-center">
                    {streamError}
                  </div>
                ) : null}

                <div className="flex gap-2 items-end">
                  <Textarea
                    value={draft}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="输入学生问题或指令..."
                    className="min-h-[44px] max-h-[160px] flex-1 resize-none bg-transparent"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void handleSend();
                      }
                    }}
                    disabled={isStreaming}
                  />
                  <Button
                    type="button"
                    onClick={() => void handleSend()}
                    disabled={!draft.trim() || isStreaming}
                    size="icon"
                    className="h-10 w-10 rounded-xl"
                    title="发送"
                  >
                    <Send className="h-4 w-4" />
                  </Button>
                </div>
                <div className="mt-2 text-[10px] text-muted-foreground/70 text-center">
                  Enter 发送 · Shift+Enter 换行 · 拖拽节点可调整位置
                </div>
              </div>
            </Panel>
          </ReactFlow>
        </div>
      </section>

      {/* Settings */}
      <aside
        className={cn(
          "shrink-0 border-l bg-muted/10 flex flex-col overflow-hidden transition-[width] duration-200 ease-in-out",
          rightPanelCollapsed ? "w-14" : "w-[320px]",
        )}
      >
        {rightPanelCollapsed ? (
          <div className="h-full flex flex-col items-center gap-2 p-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9"
              onClick={() => setRightPanelCollapsed(false)}
              title="展开右侧面板"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <div className="h-px w-7 bg-border my-1" />
            <Settings2 className="h-4 w-4 text-muted-foreground" />
          </div>
        ) : (
          <>
            <div className="p-4 border-b bg-background/50 backdrop-blur-sm flex items-center justify-between gap-2">
              <div className="font-semibold">参数</div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9"
                onClick={() => setRightPanelCollapsed(true)}
                title="折叠右侧面板"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>

            <div className="flex-1 overflow-auto p-4 space-y-4">
              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">学科</div>
                <select
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm"
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                  disabled={subjectsQuery.isLoading}
                >
                  {subjectsQuery.isLoading ? (
                    <option value={subjectName}>{subjectName}</option>
                  ) : (
                    subjectOptions.flatMap(([eduId, list]) => {
                      const eduLabel =
                        eduId === 1 ? "小学" : eduId === 2 ? "初中" : eduId === 3 ? "高中" : "其它";
                      return [
                        <optgroup key={`edu-${eduId}`} label={eduLabel}>
                          {list.map((s) => (
                            <option key={s.name} value={s.name}>
                              {s.name}
                            </option>
                          ))}
                        </optgroup>,
                      ];
                    })
                  )}
                </select>
              </div>

              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">主模型 (model)</div>
                <Input
                  value={modelOverride}
                  onChange={(e) => setModelOverride(e.target.value)}
                  placeholder="默认"
                />
              </div>

              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">子模型 (sub_model)</div>
                <Input
                  value={subModelOverride}
                  onChange={(e) => setSubModelOverride(e.target.value)}
                  placeholder="默认"
                />
              </div>

              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="h-4 w-4"
                  checked={showTools}
                  onChange={(e) => setShowTools(e.target.checked)}
                />
                显示工具消息（tool）
              </label>

              <div className="rounded-lg border bg-background/60 p-3 text-xs text-muted-foreground space-y-1">
                <div className="font-medium text-foreground">提示</div>
                <div>点击节点右上角的分叉按钮可从该消息创建新分支。</div>
                <div>分支会创建一个新的对话（后端会复制前缀消息）。</div>
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
