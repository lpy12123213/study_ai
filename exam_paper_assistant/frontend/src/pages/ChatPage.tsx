import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { Bot, Pencil, Plus, Send, Square, Trash2, User, Wrench, Search, ChevronRight, Settings2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useConversations, useConversationMessages, useCreateConversation, useDeleteConversation, useUpdateConversationTitle } from "@/hooks/useChat";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useSubjects } from "@/hooks/useSubjects";
import { apiUrl } from "@/lib/apiUrl";
import { readSseData } from "@/lib/sse";
import { cn } from "@/lib/utils";
import type { Message, Subject } from "@/types";

type UiMessage = {
  key: string;
  role: Message["role"];
  content: string;
  created_at?: string;
  tool_call_id?: string | null;
  tool_calls?: Array<Record<string, unknown>> | null;
  meta?: {
    kind?: string;
    tool_name?: string;
    iteration?: number;
  };
  isStreaming?: boolean;
};

function titleFromPrompt(prompt: string): string {
  const trimmed = prompt.trim();
  if (!trimmed) return "新对话";
  return trimmed.length > 30 ? `${trimmed.slice(0, 30)}...` : trimmed;
}

function safePrettyJson(value: unknown): string | null {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return null;
  }
}

function formatTime(iso?: string): string {
  if (!iso) return "";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return "";
  return format(dt, "HH:mm");
}

function formatToolContent(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    return safePrettyJson(parsed) ?? trimmed;
  } catch {
    return trimmed;
  }
}

function normalizeMessages(messages: Message[], showTools: boolean): UiMessage[] {
  const filtered = showTools ? messages : messages.filter((m) => m.role !== "tool");
  return filtered.map((m) => ({
    key: `msg-${m.id}`,
    role: m.role,
    content: m.content || "",
    created_at: m.created_at,
    tool_call_id: m.tool_call_id ?? null,
    tool_calls: m.tool_calls ?? null,
  }));
}

export default function ChatPage() {
  const params = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const conversationId = useMemo(() => {
    const raw = params.conversationId;
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [params.conversationId]);

  const conversationsQuery = useConversations();
  const messagesQuery = useConversationMessages(conversationId);

  const createConversation = useCreateConversation();
  const deleteConversation = useDeleteConversation();
  const updateConversationTitle = useUpdateConversationTitle();

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

  const [conversationFilter, setConversationFilter] = useState("");
  const [draft, setDraft] = useState("");

  const [uiMessages, setUiMessages] = useState<UiMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const hasLocalEditsRef = useRef(false);
  const endRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    if (!conversationId) {
      hasLocalEditsRef.current = false;
      setUiMessages([]);
      setStreamError(null);
      setIsStreaming(false);
      abortRef.current?.abort();
      abortRef.current = null;
      return;
    }

    if (!messagesQuery.data?.messages) return;
    if (isStreaming || hasLocalEditsRef.current) return;
    setUiMessages(normalizeMessages(messagesQuery.data.messages, showTools));
  }, [conversationId, messagesQuery.data?.messages, showTools, isStreaming]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [uiMessages.length, isStreaming]);

  const filteredConversations = useMemo(() => {
    const list = conversationsQuery.data ?? [];
    const q = conversationFilter.trim().toLowerCase();
    if (!q) return list;
    return list.filter((c) => (c.title || "").toLowerCase().includes(q));
  }, [conversationsQuery.data, conversationFilter]);

  const handleNewConversation = async () => {
    const created = await createConversation.mutateAsync("新对话");
    navigate(`/chat/${created.id}`);
  };

  const handleDeleteConversation = async (id: number) => {
    const ok = window.confirm("确定要删除这个对话吗？该操作不可撤销。");
    if (!ok) return;
    await deleteConversation.mutateAsync(id);
    if (conversationId === id) {
      navigate("/chat");
    }
  };

  const handleRenameConversation = async (id: number, currentTitle: string) => {
    const next = window.prompt("请输入新的对话标题：", currentTitle || "");
    const title = (next ?? "").trim();
    if (!title) return;
    await updateConversationTitle.mutateAsync({ id, title });
  };

  const stopStreaming = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    setIsStreaming(false);
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
      navigate(`/chat/${created.id}`, { replace: true });
      setUiMessages([]);
    }

    const nowIso = new Date().toISOString();
    const userKey = `local-user-${crypto.randomUUID()}`;
    const assistantKey = `local-assistant-${crypto.randomUUID()}`;

    setUiMessages((prev) => [
      ...prev,
      { key: userKey, role: "user", content: prompt, created_at: nowIso },
      {
        key: assistantKey,
        role: "assistant",
        content: "",
        created_at: nowIso,
        isStreaming: true,
      },
    ]);

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

        const type = evt.type;
        if (type === "text_delta") {
          const delta = typeof evt.content === "string" ? evt.content : "";
          assistantText += delta;
          setUiMessages((prev) =>
            prev.map((m) =>
              m.key === assistantKey
                ? { ...m, content: assistantText, isStreaming: true }
                : m,
            ),
          );
          continue;
        }

        if (type === "assistant_final") {
          const finalText =
            typeof evt.content === "string" ? evt.content : assistantText;
          assistantText = finalText;
          setUiMessages((prev) =>
            prev.map((m) =>
              m.key === assistantKey
                ? { ...m, content: finalText, isStreaming: false }
                : m,
            ),
          );
          continue;
        }

        if (!showTools) continue;

        if (type === "tool_start") {
          const toolName = typeof evt.tool_name === "string" ? evt.tool_name : "";
          const iteration =
            typeof evt.iteration === "number" ? evt.iteration : undefined;
          const args = evt.arguments ?? {};
          const prettyArgs = safePrettyJson(args) ?? String(args);

          setUiMessages((prev) => [
            ...prev,
            {
              key: `tool-start-${crypto.randomUUID()}`,
              role: "tool",
              content: prettyArgs,
              meta: { kind: "tool_start", tool_name: toolName, iteration },
            },
          ]);
          continue;
        }

        if (type === "tool_result") {
          const toolName = typeof evt.tool_name === "string" ? evt.tool_name : "";
          const iteration =
            typeof evt.iteration === "number" ? evt.iteration : undefined;
          const result = evt.result ?? {};
          const prettyResult = safePrettyJson(result) ?? String(result);

          setUiMessages((prev) => [
            ...prev,
            {
              key: `tool-result-${crypto.randomUUID()}`,
              role: "tool",
              content: prettyResult,
              meta: { kind: "tool_result", tool_name: toolName, iteration },
            },
          ]);
          continue;
        }

        if (type === "error") {
          const message =
            typeof evt.message === "string" ? evt.message : "未知错误";
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
      setUiMessages((prev) =>
        prev.map((m) =>
          m.key === assistantKey ? { ...m, isStreaming: false } : m,
        ),
      );
      hasLocalEditsRef.current = false;

      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (convId) {
        queryClient.invalidateQueries({
          queryKey: ["conversations", convId, "messages"],
        });
      }
    }
  };

  const chatTitle = messagesQuery.data?.conversation?.title || "AI 对话";

  return (
    <div className="flex h-full bg-background overflow-hidden">
      {/* Sidebar for conversations */}
      <aside className="w-[300px] shrink-0 border-r bg-muted/10 flex flex-col hidden md:flex">
        <div className="p-4 border-b space-y-3 bg-background/50 backdrop-blur-sm">
          <Button onClick={handleNewConversation} className="w-full gap-2 shadow-sm">
            <Plus className="h-4 w-4" />
            新建对话
          </Button>
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

        <div className="flex-1 overflow-y-auto p-2 scrollbar-thin">
          {conversationsQuery.isLoading ? (
            <div className="p-4 text-center text-sm text-muted-foreground animate-pulse">加载列表...</div>
          ) : filteredConversations.length === 0 ? (
            <div className="p-8 text-center text-sm text-muted-foreground">
              <div className="mx-auto mb-3 h-10 w-10 rounded-full bg-muted flex items-center justify-center">
                 <Bot className="h-5 w-5 opacity-50" />
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
                      active ? "bg-primary/10 text-primary" : "hover:bg-muted/50 text-foreground"
                    )}
                    onClick={() => navigate(`/chat/${c.id}`)}
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

                    <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-background/80 backdrop-blur-sm rounded-md shadow-sm">
                      <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    handleRenameConversation(c.id, c.title)
                                }}
                              >
                                <Pencil className="h-3 w-3" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>重命名</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      
                       <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger asChild>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-destructive hover:text-destructive hover:bg-destructive/10"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    handleDeleteConversation(c.id);
                                }}
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </TooltipTrigger>
                            <TooltipContent>删除</TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </aside>

      {/* Main Chat Area */}
      <section className="flex-1 flex flex-col min-w-0 bg-background relative">
        <header className="h-16 shrink-0 border-b flex items-center justify-between px-6 bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 z-10 sticky top-0">
          <div className="flex items-center gap-4 min-w-0">
             <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <Bot className="h-5 w-5" />
             </div>
             <div className="min-w-0">
                <h2 className="text-base font-semibold truncate">{chatTitle}</h2>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="secondary" className="h-5 px-1.5 font-normal">{subjectName}</Badge>
                    {modelOverride && <Badge variant="outline" className="h-5 px-1.5 font-normal">{modelOverride}</Badge>}
                </div>
             </div>
          </div>

          <div className="flex items-center gap-3">
             <div className="hidden sm:flex items-center gap-2">
                <select
                    className="h-8 rounded-md border border-input bg-transparent px-2 text-xs font-medium focus:ring-2 focus:ring-ring focus:ring-offset-2"
                    value={subjectName}
                    onChange={(e) => setSubjectName(e.target.value)}
                    disabled={subjectsQuery.isLoading}
                >
                    {subjectsQuery.isLoading ? (
                    <option value={subjectName}>{subjectName}</option>
                    ) : (
                    subjectOptions.flatMap(([eduId, list]) => {
                        const eduLabel = eduId === 1 ? "小学" : eduId === 2 ? "初中" : eduId === 3 ? "高中" : "其它";
                        return [
                        <optgroup key={`edu-${eduId}`} label={eduLabel}>
                            {list.map((s) => (
                            <option key={s.name} value={s.name}>{s.name}</option>
                            ))}
                        </optgroup>,
                        ];
                    })
                    )}
                </select>
             </div>

             <div className="h-6 w-px bg-border mx-1 hidden sm:block" />

             <TooltipProvider>
                 <Tooltip>
                    <TooltipTrigger asChild>
                         <Button
                            variant={showTools ? "secondary" : "ghost"}
                            size="icon"
                            className="h-8 w-8"
                            onClick={() => setShowTools(!showTools)}
                         >
                            <Wrench className="h-4 w-4" />
                         </Button>
                    </TooltipTrigger>
                    <TooltipContent>显示工具调用详情</TooltipContent>
                 </Tooltip>
             </TooltipProvider>

             <TooltipProvider>
                 <Tooltip>
                    <TooltipTrigger asChild>
                         <details className="relative">
                            <summary className="list-none cursor-pointer">
                                <Button variant="ghost" size="icon" className="h-8 w-8">
                                    <Settings2 className="h-4 w-4" />
                                </Button>
                            </summary>
                            <div className="absolute right-0 top-full mt-2 w-72 rounded-lg border bg-popover p-4 shadow-md z-50">
                                <h4 className="font-medium text-sm mb-3">高级模型设置</h4>
                                <div className="space-y-3">
                                    <div className="space-y-1">
                                        <label className="text-xs text-muted-foreground">主模型 (Model)</label>
                                        <Input
                                            className="h-8 text-sm"
                                            value={modelOverride}
                                            onChange={(e) => setModelOverride(e.target.value)}
                                            placeholder="默认"
                                        />
                                    </div>
                                    <div className="space-y-1">
                                        <label className="text-xs text-muted-foreground">子模型 (Sub Model)</label>
                                        <Input
                                            className="h-8 text-sm"
                                            value={subModelOverride}
                                            onChange={(e) => setSubModelOverride(e.target.value)}
                                            placeholder="默认"
                                        />
                                    </div>
                                </div>
                            </div>
                         </details>
                    </TooltipTrigger>
                    <TooltipContent>高级参数设置</TooltipContent>
                 </Tooltip>
             </TooltipProvider>

            {isStreaming && (
                <Button variant="destructive" size="sm" onClick={stopStreaming} className="h-8 gap-1.5 shadow-sm">
                    <Square className="h-3 w-3 fill-current" />
                    停止
                </Button>
            )}
          </div>
        </header>

        <div className="flex-1 overflow-y-auto px-4 py-6 scroll-smooth">
          <div className="mx-auto max-w-3xl space-y-6">
             {/* Empty State */}
             {!conversationId && uiMessages.length === 0 && (
                <motion.div 
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex flex-col items-center justify-center py-20 text-center"
                >
                    <div className="h-16 w-16 bg-primary/5 rounded-2xl flex items-center justify-center mb-6">
                        <Bot className="h-8 w-8 text-primary" />
                    </div>
                    <h2 className="text-2xl font-bold mb-2">我是您的智能组卷助手</h2>
                    <p className="text-muted-foreground max-w-md mb-8">
                        我可以帮您检索题目、组合试卷、并整理成文档。请告诉我您需要的试卷类型。
                    </p>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-w-2xl w-full text-left">
                        {[
                            "帮我生成一份高一数学函数练习卷",
                            "找几道关于牛顿运动定律的物理题",
                            "初中英语阅读理解专项训练",
                            "查看最近保存的试卷"
                        ].map((suggestion, i) => (
                             <Button
                                key={i}
                                variant="outline"
                                className="h-auto py-3 px-4 justify-start font-normal text-muted-foreground hover:text-foreground hover:border-primary/50 whitespace-normal"
                                onClick={() => setDraft(suggestion)}
                             >
                                {suggestion}
                             </Button>
                        ))}
                    </div>
                </motion.div>
             )}

             {/* Messages */}
             <AnimatePresence initial={false}>
                 {uiMessages.map((m) => {
                    const isUser = m.role === "user";
                    const isTool = m.role === "tool";

                    if (isTool) {
                        return (
                            <motion.div
                                key={m.key}
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: "auto" }}
                                exit={{ opacity: 0, height: 0 }}
                                className="pl-12"
                            >
                                <details className="group rounded-md border border-border/50 bg-muted/30 px-3 py-2 text-xs">
                                    <summary className="flex cursor-pointer items-center gap-2 select-none text-muted-foreground group-hover:text-foreground transition-colors">
                                        <Wrench className="h-3.5 w-3.5" />
                                        <span>调用工具: {m.meta?.tool_name || "Unknown"}</span>
                                        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90 ml-auto opacity-50" />
                                    </summary>
                                    <div className="mt-2 pt-2 border-t border-border/50 font-mono overflow-x-auto">
                                        {formatToolContent(m.content)}
                                    </div>
                                </details>
                            </motion.div>
                        );
                    }

                    return (
                        <motion.div
                            key={m.key}
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className={cn("flex gap-4 group", isUser ? "flex-row-reverse" : "")}
                        >
                            <div className={cn(
                                "h-8 w-8 rounded-lg flex items-center justify-center shrink-0 shadow-sm mt-1",
                                isUser ? "bg-primary text-primary-foreground" : "bg-muted text-foreground border"
                            )}>
                                {isUser ? <User className="h-5 w-5" /> : <Bot className="h-5 w-5" />}
                            </div>

                            <div className={cn(
                                "flex flex-col max-w-[85%]",
                                isUser ? "items-end" : "items-start"
                            )}>
                                <div className="flex items-center gap-2 mb-1 px-1">
                                    <span className="text-xs font-medium text-muted-foreground">
                                        {isUser ? "你" : "AI 助手"}
                                    </span>
                                    <span className="text-[10px] text-muted-foreground/50 tabular-nums">
                                        {formatTime(m.created_at)}
                                    </span>
                                </div>
                                <div className={cn(
                                    "rounded-2xl px-5 py-3.5 text-sm leading-relaxed shadow-sm whitespace-pre-wrap",
                                    isUser 
                                        ? "bg-primary text-primary-foreground rounded-tr-sm" 
                                        : "bg-card border rounded-tl-sm text-foreground"
                                )}>
                                    {m.content}
                                    {m.isStreaming && (
                                        <span className="ml-1.5 inline-block h-3 w-1.5 animate-pulse bg-current/50 rounded-full align-middle" />
                                    )}
                                </div>
                                {m.role === "assistant" && (m.tool_calls?.length ?? 0) > 0 && (
                                    <div className="mt-1 px-1">
                                        <Badge variant="outline" className="text-[10px] h-5 gap-1 font-normal text-muted-foreground bg-transparent border-transparent">
                                            <Wrench className="h-3 w-3" />
                                            使用了 {m.tool_calls?.length} 个工具
                                        </Badge>
                                    </div>
                                )}
                            </div>
                        </motion.div>
                    );
                 })}
             </AnimatePresence>

             {streamError && (
                 <motion.div 
                    initial={{ opacity: 0 }} 
                    animate={{ opacity: 1 }}
                    className="rounded-lg border border-destructive/50 bg-destructive/5 p-3 text-sm text-destructive text-center"
                >
                    {streamError}
                 </motion.div>
             )}

             <div ref={endRef} className="h-px" />
          </div>
        </div>

        {/* Input Area */}
        <div className="p-4 bg-background border-t">
            <div className="mx-auto max-w-3xl relative">
                <div className="relative rounded-2xl border bg-muted/30 shadow-sm focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary focus-within:bg-background transition-all">
                    <Textarea
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        placeholder="输入你的指令..."
                        className="min-h-[50px] max-h-[200px] w-full resize-none border-0 bg-transparent px-4 py-3 focus-visible:ring-0 placeholder:text-muted-foreground/70"
                        onKeyDown={(e) => {
                            if (e.key === "Enter" && !e.shiftKey) {
                                e.preventDefault();
                                handleSend();
                            }
                        }}
                        disabled={isStreaming}
                    />
                    <div className="flex justify-between items-center px-2 pb-2">
                        <div className="text-xs text-muted-foreground px-2">
                             Enter 发送 · Shift+Enter 换行
                        </div>
                        <Button
                            onClick={() => void handleSend()}
                            disabled={!draft.trim() || isStreaming}
                            size="icon"
                            className={cn(
                                "h-8 w-8 rounded-xl transition-all",
                                draft.trim() ? "opacity-100 scale-100" : "opacity-50 scale-90"
                            )}
                        >
                            <Send className="h-4 w-4" />
                        </Button>
                    </div>
                </div>
                <div className="text-center mt-2 text-[10px] text-muted-foreground/60">
                    AI 内容生成可能由于网络原因延迟，请耐心等待。
                </div>
            </div>
        </div>
      </section>
    </div>
  );
}
