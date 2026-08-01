import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router";
import {
  AlertCircle,
  Brain,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Copy,
  GitBranch,
  RotateCcw,
  Sparkles,
  Square,
  Trophy,
  X,
  XCircle,
} from "lucide-react";

import { submitDeepThink } from "@/features/deepthink/api";
import {
  deepthinkProjectionReducer,
  initialDeepthinkProjection,
  type DtNode,
} from "@/features/deepthink/model/projection";
import { tasksApi } from "@/features/task-center/api";
import { ApiError } from "@/shared/api/http-client";
import { watchTask, type TaskWatchHandle } from "@/shared/streaming/task-coordinator";
import { useTasksStore } from "@/stores/tasks";
import { formatDuration } from "@/lib/format";
import { proxyImageUrl } from "@/lib/media";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownView } from "@/components/markdown/markdown-view";
import { SubjectSelect } from "@/components/question/subject-select";

const ACTIVE_RUN_KEY = "study-ai:deepthink:active-run";

interface PersistedRun {
  taskId: string;
  lastSeq: number;
  question: string;
  subject: string;
}

function readPersistedRun(): PersistedRun | null {
  try {
    const raw = localStorage.getItem(ACTIVE_RUN_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PersistedRun>;
    if (typeof value.taskId !== "string" || typeof value.question !== "string") return null;
    return {
      taskId: value.taskId,
      lastSeq: typeof value.lastSeq === "number" ? value.lastSeq : 0,
      question: value.question,
      subject: typeof value.subject === "string" ? value.subject : "",
    };
  } catch {
    return null;
  }
}

function writePersistedRun(run: PersistedRun): void {
  try {
    localStorage.setItem(ACTIVE_RUN_KEY, JSON.stringify(run));
  } catch {
    // 本地存储不可用不阻塞生成。
  }
}

function clearPersistedRun(): void {
  try {
    localStorage.removeItem(ACTIVE_RUN_KEY);
  } catch {
    // 本地存储不可用时无需额外处理。
  }
}

function nodeStatusIcon(status: string) {
  switch (status) {
    case "final":
      return <Trophy className="size-4 text-success" />;
    case "selected":
      return <CheckCircle2 className="size-4 text-primary" />;
    case "pruned":
      return <XCircle className="size-4 text-muted-foreground" />;
    case "evaluated":
      return <CheckCircle2 className="size-4 text-muted-foreground" />;
    default:
      return <CircleDashed className="size-4 text-muted-foreground" />;
  }
}

function NodeCard({ node, index, inBestPath }: { node: DtNode; index: number; inBestPath: boolean }) {
  return (
    <div
      className={cn(
        "animate-fade-in rounded-lg border border-border bg-background p-3 text-sm",
        inBestPath && "border-primary/40 ring-2 ring-primary",
        node.status === "pruned" && "opacity-60",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 shrink-0">{nodeStatusIcon(node.status)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium text-muted-foreground">#{index}</span>
            <Badge variant="outline">第 {node.depth} 层</Badge>
            {node.score != null ? (
              <Badge variant={node.status === "pruned" ? "muted" : "secondary"}>{node.score.toFixed(1)} 分</Badge>
            ) : null}
            {node.isFinal ? <Badge variant="outline">终局</Badge> : null}
            {inBestPath ? <Badge>最佳路径</Badge> : null}
          </div>
          <p className="mt-1.5 leading-relaxed">{node.thought || "（未命名步骤）"}</p>
          {node.reasoning ? (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-muted-foreground">{node.reasoning}</p>
          ) : null}
          {node.status === "pruned" && node.pruneReason ? (
            <p className="mt-1 text-xs text-muted-foreground">剪枝原因：{node.pruneReason}</p>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ImagePreview({ url }: { url: string }) {
  const [failed, setFailed] = useState(false);
  const src = proxyImageUrl(url);
  if (!src) return null;
  if (failed) {
    return <p className="text-xs text-muted-foreground">图片预览加载失败，提交时仍会携带该链接。</p>;
  }
  return (
    <img
      src={src}
      alt="题目图片预览"
      className="max-h-32 rounded-md border border-border object-contain"
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
    />
  );
}

function friendlyStreamError(err: Error): string {
  if (err instanceof ApiError) {
    if (err.code === "llm_not_configured") return "未配置 LLM 服务，请先在设置页配置模型后再试";
    if (err.status === 401) return "登录状态已失效，请重新登录";
    return err.message || `请求失败（${err.code}）`;
  }
  return "网络异常，请确认后端服务已启动";
}

export function DeepthinkPage() {
  const toast = useUiStore((s) => s.toast);
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  // 输入区（question 支持首页 Intent Workspace 预填）
  const [question, setQuestion] = useState(
    () => (location.state as { prefillQuestion?: string } | null)?.prefillQuestion ?? "",
  );
  const [subject, setSubject] = useState("");
  const [imageUrl, setImageUrl] = useState("");

  // 运行区：事件投影收敛到 reducer（对齐 chat/study-materials 模式）
  const [run, dispatch] = useReducer(deepthinkProjectionReducer, initialDeepthinkProjection());
  const {
    phase,
    stopped,
    errorMsg,
    searchInfo,
    depthInfo,
    nodes,
    bestPathIds,
    answerStarted,
    answer,
    reasoning,
    doneInfo,
  } = run;
  const [reasoningOpen, setReasoningOpen] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const watcherRef = useRef<TaskWatchHandle | null>(null);
  // 权威的当前任务 id：提交返回后即写入，不等首个事件回填，stop 才能准确取消。
  const taskIdRef = useRef<string | null>(null);
  const resumeProbeRef = useRef("");
  const lastPersistAtRef = useRef(0);
  const nodeListRef = useRef<HTMLDivElement | null>(null);
  const answerScrollRef = useRef<HTMLDivElement | null>(null);

  // 卸载时中断提交并关闭事件流（流只能由用户动作/恢复触发，effect 里不启动 SSE）
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      watcherRef.current?.close();
    };
  }, []);

  // 新节点出现时滚动到底部
  useEffect(() => {
    const el = nodeListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [nodes.length, phase]);

  // 解答流式输出时跟随滚动
  useEffect(() => {
    if (phase !== "running") return;
    const el = answerScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [answer, phase]);

  /** 节流持久化 {taskId,lastSeq,question,subject} 并同步 URL 深链。 */
  const persistRun = useCallback(
    (taskId: string, lastSeq: number, q: string, subj: string) => {
      const now = Date.now();
      if (now - lastPersistAtRef.current < 500) return;
      lastPersistAtRef.current = now;
      writePersistedRun({ taskId, lastSeq, question: q, subject: subj });
      setSearchParams({ task: taskId }, { replace: true });
    },
    [setSearchParams],
  );

  /**
   * 用 Task Coordinator 订阅任务流：REST 校准 + 断线重连，事件归一到投影，
   * 同时转发给任务中心 store 以支持深链。
   */
  const beginWatch = useCallback(
    (taskId: string, afterSeq: number, q: string, subj: string) => {
      watcherRef.current?.close();
      const taskStore = useTasksStore.getState();
      taskStore.register(taskId, { type: "deepthink", title: `深度解题：${subj || "高中数学"}` });
      const watcher = watchTask(taskId, {
        afterSeq,
        getStatus: async (id) => {
          const detail = await tasksApi.get(id);
          return { status: String(detail.status || ""), result: detail.result, error: detail.error };
        },
        onEvent: (ev) => {
          dispatch({ type: "event", ev });
          // answer/reasoning 增量事件可送入任务中心 store；DeepThink 无 text_delta 快照。
          if (ev.type !== "text_delta") taskStore.applyEvent(taskId, ev);
          persistRun(taskId, ev.seq || afterSeq, q, subj);
        },
        onCalibrated: (rest) => {
          // 校准发现终态（completed/canceled/failed）：投影据此对齐
          dispatch({ type: "calibrate", status: String(rest.status || "") });
        },
        onTerminal: () => {
          clearPersistedRun();
          setSearchParams({}, { replace: true });
        },
        onGaveUp: () => {
          dispatch({ type: "stream_error", message: "连接断开；服务端任务可能仍在继续运行" });
        },
      });
      watcherRef.current = watcher;
    },
    [persistRun, setSearchParams],
  );

  const start = async () => {
    const q = question.trim();
    if (!q) {
      toast({ title: "请输入题目", description: "题目内容不能为空", variant: "warning" });
      return;
    }
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    watcherRef.current?.close();
    watcherRef.current = null;

    dispatch({ type: "start" });
    setReasoningOpen(false);
    clearPersistedRun();
    setSearchParams({}, { replace: true });

    const payload: { question: string; subject?: string; image_url?: string } = { question: q };
    if (subject) payload.subject = subject;
    const img = imageUrl.trim();
    if (img) payload.image_url = img;

    try {
      const { taskId } = await submitDeepThink(payload, { signal: ctrl.signal });
      if (ctrl.signal.aborted) return;
      taskIdRef.current = taskId;
      // 阻止恢复探测重复 watch 刚提交的任务
      resumeProbeRef.current = taskId;
      writePersistedRun({ taskId, lastSeq: 0, question: q, subject });
      setSearchParams({ task: taskId }, { replace: true });
      beginWatch(taskId, 0, q, subject);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      dispatch({ type: "stream_error", message: friendlyStreamError(err instanceof Error ? err : new Error(String(err))) });
    }
  };

  const stop = async () => {
    const taskId = taskIdRef.current ?? run.taskId;
    dispatch({ type: "stop_requested" });
    if (taskId) {
      try {
        await tasksApi.cancel(taskId);
        dispatch({ type: "server_cancel_confirmed" });
      } catch {
        // 取消请求失败（离线等）也要中断本地接收，不能死路。
      }
    }
    watcherRef.current?.close();
    watcherRef.current = null;
    taskIdRef.current = null;
    dispatch({ type: "stopped" });
    clearPersistedRun();
    setSearchParams({}, { replace: true });
  };

  const resetAll = () => {
    abortRef.current?.abort();
    watcherRef.current?.close();
    watcherRef.current = null;
    taskIdRef.current = null;
    dispatch({ type: "clear" });
    setReasoningOpen(false);
    clearPersistedRun();
    setSearchParams({}, { replace: true });
    setQuestion("");
    setSubject("");
    setImageUrl("");
  };

  const backToEdit = () => {
    abortRef.current?.abort();
    watcherRef.current?.close();
    watcherRef.current = null;
    taskIdRef.current = null;
    dispatch({ type: "back_to_edit" });
    clearPersistedRun();
    setSearchParams({}, { replace: true });
  };

  const copyAnswer = async () => {
    try {
      await navigator.clipboard.writeText(answer);
      toast({ title: "已复制答案", variant: "success" });
    } catch {
      toast({ title: "复制失败", description: "浏览器拒绝访问剪贴板", variant: "destructive" });
    }
  };

  // 刷新/深链恢复：存在持久化或 URL taskId 时探测状态，running/completed 续播（全量回放重建投影），
  // canceled/failed 对齐投影。
  useEffect(() => {
    const persisted = readPersistedRun();
    const taskId = searchParams.get("task") || persisted?.taskId;
    if (!taskId || resumeProbeRef.current === taskId) return;
    resumeProbeRef.current = taskId;

    let cancelled = false;
    void (async () => {
      let status = "";
      try {
        const detail = await tasksApi.get(taskId);
        status = String(detail.status || "");
      } catch {
        if (!cancelled) {
          clearPersistedRun();
          setSearchParams({}, { replace: true });
        }
        return;
      }
      if (cancelled) return;

      if (status === "running" || status === "completed") {
        const q = persisted?.question ?? "";
        const subj = persisted?.subject ?? "";
        if (q) setQuestion(q);
        if (subj) setSubject(subj);
        taskIdRef.current = taskId;
        dispatch({ type: "restore", taskId, lastSeq: 0 });
        setReasoningOpen(false);
        // 空投影全量回放，重建节点与解答内容
        beginWatch(taskId, 0, q, subj);
      } else if (status === "canceled" || status === "failed") {
        dispatch({ type: "calibrate", status });
        clearPersistedRun();
        setSearchParams({}, { replace: true });
      } else {
        clearPersistedRun();
        setSearchParams({}, { replace: true });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [searchParams, beginWatch, setSearchParams]);

  // ---------------- 输入视图 ----------------
  if (phase === "idle") {
    return (
      <div className="mx-auto max-w-2xl animate-fade-in">
        <div className="flex flex-col items-center gap-3 pb-6 pt-10 text-center">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lift">
            <Brain className="size-7" />
          </div>
          <h1 className="text-xl font-semibold tracking-tight">DeepThink 深度解题</h1>
          <p className="text-sm text-muted-foreground">多路径探索式深度解题，展示完整推理过程</p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>输入题目</CardTitle>
            <CardDescription>提交后将并行探索多条推理路径，评估剪枝后基于最优路径生成解答</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void start();
              }}
              className="space-y-4"
            >
              <div className="space-y-1.5">
                <Label htmlFor="dt-question">题目</Label>
                <Textarea
                  id="dt-question"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  placeholder="输入一道难题，支持 LaTeX 如 $x^2+y^2=1$"
                  rows={5}
                  maxLength={12000}
                  className="resize-y"
                  autoFocus
                />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>学科（可选）</Label>
                  <div className="flex items-center gap-1.5">
                    <SubjectSelect
                      value={subject || undefined}
                      onValueChange={setSubject}
                      placeholder="不指定"
                      className="flex-1"
                    />
                    {subject ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label="清除学科"
                        onClick={() => setSubject("")}
                      >
                        <X />
                      </Button>
                    ) : null}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="dt-image">题目图片链接（可选）</Label>
                  <Input
                    id="dt-image"
                    value={imageUrl}
                    onChange={(e) => setImageUrl(e.target.value)}
                    placeholder="https://…"
                    maxLength={2000}
                  />
                </div>
              </div>
              {imageUrl.trim() ? <ImagePreview key={imageUrl.trim()} url={imageUrl.trim()} /> : null}
              <Button type="submit" className="w-full" disabled={!question.trim()}>
                <Sparkles />
                开始解题
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ---------------- 运行 / 完成 / 失败视图 ----------------
  const cfg = searchInfo?.config;
  const explorationStatus = bestPathIds
    ? "已锁定最佳路径，正在生成解答"
    : depthInfo
      ? `已完成第 ${depthInfo.depth} 层探索 · 前沿 ${depthInfo.frontierSize} 个分支 · 累计 ${depthInfo.totalNodes} 个节点`
      : searchInfo
        ? "正在检索与扩展解题路径"
        : "正在提交任务";
  const totalNodes = doneInfo?.totalNodes ?? (nodes.length > 0 ? nodes.length : null);

  return (
    <div className="mx-auto max-w-6xl animate-fade-in space-y-5">
      {/* 状态工具行 */}
      <div className="flex flex-wrap items-center gap-3">
        {phase === "running" ? (
          <>
            <Spinner />
            <span className="text-sm text-muted-foreground">DeepThink 正在多路径探索解题…</span>
            <Button type="button" variant="outline" size="sm" className="ml-auto" onClick={stop}>
              <Square />
              停止接收
            </Button>
          </>
        ) : null}
        {phase === "done" ? (
          <>
            <Badge variant={stopped ? "warning" : "success"}>{stopped ? "已停止接收" : "已完成"}</Badge>
            {doneInfo?.elapsed != null ? (
              <span className="text-xs text-muted-foreground">耗时 {formatDuration(doneInfo.elapsed)}</span>
            ) : null}
            {totalNodes != null ? (
              <span className="text-xs text-muted-foreground">探索节点 {totalNodes}</span>
            ) : null}
            {doneInfo?.bestScore != null ? (
              <span className="text-xs text-muted-foreground">最佳得分 {doneInfo.bestScore.toFixed(1)}</span>
            ) : null}
            <div className="ml-auto flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={copyAnswer} disabled={!answer}>
                <Copy />
                复制答案
              </Button>
              <Button type="button" size="sm" onClick={resetAll}>
                <RotateCcw />
                新问题
              </Button>
            </div>
          </>
        ) : null}
        {phase === "error" ? (
          <div className="ml-auto flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={start}>
              <RotateCcw />
              重试
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={backToEdit}>
              返回编辑
            </Button>
          </div>
        ) : null}
      </div>

      {phase === "error" && errorMsg ? (
        <Alert variant="destructive">
          <AlertCircle />
          <AlertDescription>{errorMsg}</AlertDescription>
        </Alert>
      ) : null}

      {/* 题目摘要 */}
      <div className="line-clamp-2 rounded-lg border border-border bg-muted/40 px-4 py-2.5 text-sm text-muted-foreground">
        {searchInfo?.question || question}
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* 左：探索过程 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <GitBranch className="size-4 text-primary" />
              探索过程
            </CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span>{explorationStatus}</span>
              {searchInfo?.subject ? <Badge variant="outline">{searchInfo.subject}</Badge> : null}
              {cfg ? (
                <span className="text-xs">
                  分支 {String(cfg.branch_factor ?? "—")} · 波束 {String(cfg.beam_width ?? "—")} · 深度{" "}
                  {String(cfg.max_depth ?? "—")}
                </span>
              ) : null}
            </CardDescription>
          </CardHeader>
          <CardContent>
            {nodes.length === 0 ? (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                <Spinner />
                正在等待推理节点生成…
              </div>
            ) : (
              <div ref={nodeListRef} className="max-h-[560px] space-y-2 overflow-y-auto pr-1">
                {nodes.map((n, i) => (
                  <NodeCard key={n.id} node={n} index={i + 1} inBestPath={bestPathIds?.has(n.id) ?? false} />
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* 右：解答 */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Sparkles className="size-4 text-primary" />
              解答
            </CardTitle>
            <CardDescription>
              {phase === "running"
                ? answerStarted
                  ? "正在基于最优路径流式生成解答…"
                  : "等待探索完成后生成解答…"
                : "基于最优推理路径的完整解答"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {reasoning ? (
              <div className="rounded-lg border border-border">
                <button
                  type="button"
                  className="flex w-full items-center gap-2 px-3 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  onClick={() => setReasoningOpen((v) => !v)}
                >
                  {reasoningOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                  推理过程（{reasoning.length} 字）
                </button>
                {reasoningOpen ? (
                  <div className="max-h-56 overflow-y-auto whitespace-pre-wrap border-t border-border px-3 py-2 text-xs leading-relaxed text-muted-foreground">
                    {reasoning}
                  </div>
                ) : null}
              </div>
            ) : null}

            {answer ? (
              <div ref={answerScrollRef} className="max-h-[560px] overflow-y-auto pr-1">
                <MarkdownView content={answer} />
                {phase === "running" ? (
                  <span className="mt-1 inline-block h-4 w-1.5 animate-pulse bg-primary/70" />
                ) : null}
              </div>
            ) : (
              <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                {phase === "running" ? (
                  <>
                    <Spinner />
                    解答将在探索完成后在此流式输出…
                  </>
                ) : (
                  "（暂无解答内容）"
                )}
              </div>
            )}

            {stopped && phase === "done" ? (
              <p className="text-xs text-muted-foreground">已停止接收；服务端任务可能仍在运行，以上内容可能不完整。</p>
            ) : null}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
