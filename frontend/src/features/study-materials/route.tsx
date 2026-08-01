import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  BookOpenText,
  Bot,
  CheckCircle2,
  ChevronDown,
  FileText,
  History,
  PanelLeftOpen,
  Plus,
  RotateCcw,
  SlidersHorizontal,
  Sparkles,
  Undo2,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import {
  generateStudyMaterials,
  studyArchivesApi,
  studyMaterialsApi,
  type StudyGeneratePayload,
} from "@/features/study-materials/api";
import { tasksApi } from "@/features/task-center/api";
import {
  STUDY_PRESETS,
  type StudyPreset,
  type TaskEvent,
} from "@/shared/api/types";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";
import { SubjectSelect } from "@/components/question/subject-select";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MarkdownView } from "@/components/markdown/markdown-view";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { ToolStepView } from "@/features/chat/model/types";
import { AssistantTurn } from "@/features/chat/ui/assistant-turn";
import { PromptComposer } from "@/features/chat/ui/prompt-composer";
import { ToolInspectorHost } from "@/features/chat/ui/tool-inspector-host";
import {
  initialStudyMaterialsProjection,
  studyMaterialsProjectionReducer,
  type StudyMaterialsProjectionAction,
  type StudyMaterialsStreamEndReason,
} from "./model/reducer";
import {
  selectKnowledgePointBoard,
  selectResultMarkdown,
  selectStageSummary,
  selectToolCount,
} from "./model/selectors";
import { resolveResumeAfterSeq } from "./model/resume";
import type { StudyMaterialsProjection } from "./model/types";
import { decodeStudyMaterialsEvent } from "./streaming/contract";
import { KnowledgePointBoard } from "./ui/knowledge-point-board";
import { MaterialResultCard } from "./ui/material-result-card";
import { MaterialsWelcome } from "./ui/materials-welcome";
import { ProcessPanel, StudyTodoProgress } from "./ui/process-panel";
import { RecoveryCard } from "./ui/recovery-card";
import { ResumeBanner } from "./ui/resume-banner";
import { RevisionStrip } from "./ui/revision-strip";
import { StageProgress } from "./ui/stage-progress";
import { StudyMaterialsUserRequest } from "./ui/user-request";

interface GenerationFlags {
  with_questions: boolean;
  with_diagrams: boolean;
  enable_extra_tools: boolean;
  prefer_local_archive: boolean;
}

interface ActiveRequest {
  query: string;
  subject: string;
  preset: StudyPreset;
  requirements: string;
  flags: GenerationFlags;
  maxPoints?: number;
}

interface PersistedRun extends ActiveRequest {
  taskId: string;
  lastSeq: number;
}

interface ResumeCandidate {
  taskId: string;
  query: string;
  /** 任务中心状态：completed 时 ResumeBanner 切换为「恢复视图」语义。 */
  status?: string;
  persisted?: PersistedRun;
}

const ACTIVE_RUN_KEY = "study-ai:study-materials:active-run";

const DEFAULT_FLAGS: GenerationFlags = {
  with_questions: false,
  with_diagrams: true,
  enable_extra_tools: false,
  prefer_local_archive: true,
};

function readPersistedRun(): PersistedRun | null {
  try {
    const raw = localStorage.getItem(ACTIVE_RUN_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PersistedRun>;
    if (
      typeof value.taskId !== "string" ||
      typeof value.query !== "string" ||
      typeof value.preset !== "string"
    ) {
      return null;
    }
    return {
      taskId: value.taskId,
      query: value.query,
      subject: typeof value.subject === "string" ? value.subject : "",
      preset: value.preset as StudyPreset,
      requirements: typeof value.requirements === "string" ? value.requirements : "",
      flags: { ...DEFAULT_FLAGS, ...(value.flags ?? {}) },
      ...(typeof value.maxPoints === "number" ? { maxPoints: value.maxPoints } : {}),
      lastSeq: typeof value.lastSeq === "number" ? value.lastSeq : 0,
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

function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message || error.code;
  if (error instanceof Error) return error.message;
  return "操作失败，请稍后重试";
}

function AssistantShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-full bg-spectral/10 text-spectral">
        <Bot className="size-4" />
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function GenerationOptions({
  requirements,
  onRequirementsChange,
  flags,
  onFlagsChange,
  maxPoints,
  onMaxPointsChange,
}: {
  requirements: string;
  onRequirementsChange: (value: string) => void;
  flags: GenerationFlags;
  onFlagsChange: (flags: GenerationFlags) => void;
  maxPoints?: number;
  onMaxPointsChange: (value: number | undefined) => void;
}) {
  const selected = Object.values(flags).filter(Boolean).length + (maxPoints !== undefined ? 1 : 0);
  const items: Array<{ key: keyof GenerationFlags; label: string; description: string }> = [
    { key: "with_questions", label: "包含练习题", description: "在讲义中加入典型例题或练习" },
    { key: "with_diagrams", label: "生成示意图", description: "需要时生成教学示意图" },
    { key: "enable_extra_tools", label: "扩展检索来源", description: "允许检索更多公开资料来源" },
    { key: "prefer_local_archive", label: "优先本地档案", description: "先复用相同主题的已验收资料" },
  ];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <SlidersHorizontal />
          选项 {selected} 项
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-80 space-y-4">
        <div>
          <div className="text-sm font-semibold">生成选项</div>
          <div className="mt-0.5 text-xs text-muted-foreground">这些设置会随本次任务一并提交。</div>
        </div>
        <div className="space-y-3">
          {items.map((item) => (
            <div key={item.key} className="flex items-start justify-between gap-3">
              <div>
                <Label htmlFor={`materials-${item.key}`} className="text-sm">
                  {item.label}
                </Label>
                <div className="mt-0.5 text-xs leading-5 text-muted-foreground">{item.description}</div>
              </div>
              <Switch
                id={`materials-${item.key}`}
                checked={flags[item.key]}
                onCheckedChange={(checked) => onFlagsChange({ ...flags, [item.key]: checked })}
              />
            </div>
          ))}
          <div className="flex items-start justify-between gap-3">
            <div>
              <Label htmlFor="materials-max-points" className="text-sm">
                知识点上限
              </Label>
              <div className="mt-0.5 text-xs leading-5 text-muted-foreground">
                1–15 个；留空使用预设默认值
              </div>
            </div>
            <Input
              id="materials-max-points"
              type="number"
              min={1}
              max={15}
              placeholder="默认"
              className="h-8 w-20"
              value={maxPoints ?? ""}
              onChange={(event) => {
                const raw = event.target.value.trim();
                if (!raw) {
                  onMaxPointsChange(undefined);
                  return;
                }
                const value = Number(raw);
                if (!Number.isFinite(value)) return;
                onMaxPointsChange(Math.max(1, Math.min(15, Math.round(value))));
              }}
            />
          </div>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="materials-requirements">额外要求</Label>
          <Textarea
            id="materials-requirements"
            value={requirements}
            onChange={(event) => onRequirementsChange(event.target.value)}
            placeholder="例如：更通俗、偏推导、多配典型例题"
            rows={3}
          />
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** 骨架占位符：BACKBONE 之后的 text_snapshot 可能残留 [[FILL:xxx]] / [[FIG:n]]。 */
const SKELETON_PLACEHOLDER_RE = /\[\[(?:FILL:[^\]]+|FIG:\d+)\]\]/g;

/** 渲染前把骨架占位符替换为「撰写中」灰块（不动 markdown-view 组件）。 */
function renderSkeletonPlaceholders(markdown: string): string {
  return markdown.replace(SKELETON_PLACEHOLDER_RE, "\n\n> **撰写中…**\n\n");
}

/** 运行中的草稿预览：text_delta 为完整快照，修订时整体替换。 */
function DraftPreviewPane({ markdown, version }: { markdown: string; version: number }) {
  const [open, setOpen] = useState(true);
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left"
        aria-expanded={open}
      >
        <span className="flex min-w-0 items-center gap-2 text-xs font-semibold text-muted-foreground">
          <FileText className="size-3.5 shrink-0" />
          <span className="truncate">草稿预览 · 修订中会自动更新</span>
          {version > 0 ? <Badge variant="outline">第 {version} 版草稿</Badge> : null}
        </span>
        <ChevronDown
          className={cn("size-4 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {open ? (
        <div className="max-h-96 overflow-y-auto border-t border-border px-4 py-3">
          <MarkdownView content={renderSkeletonPlaceholders(markdown)} />
        </div>
      ) : null}
    </section>
  );
}

/** 流在 task_started 之前失败：服务端没有可恢复记录，提供同参重试。 */
function EarlyRetryNotice({ onRetry, disabled }: { onRetry: () => void; disabled?: boolean }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-soft">
      <p className="min-w-0 flex-1 text-xs leading-5 text-muted-foreground">
        任务在启动前中断，服务端没有留下可恢复的记录。可以使用相同请求直接重试。
      </p>
      <Button size="sm" variant="outline" onClick={onRetry} disabled={disabled}>
        <RotateCcw /> 重试生成
      </Button>
    </div>
  );
}

export function StudyMaterialsRoute() {
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const toast = useUiStore((state) => state.toast);

  const [draft, setDraft] = useState(
    () => (location.state as { prefillQuery?: string } | null)?.prefillQuery ?? "",
  );
  const [subject, setSubject] = useState("");
  const [preset, setPreset] = useState<StudyPreset>("standard");
  const [requirements, setRequirements] = useState("");
  const [flags, setFlags] = useState<GenerationFlags>(DEFAULT_FLAGS);
  const [maxPoints, setMaxPoints] = useState<number | undefined>(undefined);
  const [activeRequest, setActiveRequest] = useState<ActiveRequest | null>(null);
  const [projection, setProjection] = useState<StudyMaterialsProjection>(
    initialStudyMaterialsProjection,
  );
  const [receiving, setReceiving] = useState(false);
  const [resumeCandidate, setResumeCandidate] = useState<ResumeCandidate | null>(null);
  const [inspectorToolId, setInspectorToolId] = useState<string | null>(null);
  const [latexUrl, setLatexUrl] = useState<string | undefined>();
  const [pinnedToBottom, setPinnedToBottom] = useState(true);
  /** 宽屏双栏：过程面板折叠；窄屏（<lg）：过程/文稿单栏 tabs。 */
  const [processCollapsed, setProcessCollapsed] = useState(false);
  const [mobileTab, setMobileTab] = useState<"process" | "document">("process");

  const projectionRef = useRef(projection);
  const activeRequestRef = useRef(activeRequest);
  const abortRef = useRef<AbortController | null>(null);
  const streamEpochRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  // 已探测过的 taskId：同一任务只探测一次，点击不同最近任务仍可触发。
  const resumeProbeRef = useRef("");

  useEffect(() => {
    projectionRef.current = projection;
  }, [projection]);

  useEffect(() => {
    activeRequestRef.current = activeRequest;
  }, [activeRequest]);

  useEffect(
    () => () => {
      streamEpochRef.current += 1;
      abortRef.current?.abort();
    },
    [],
  );

  const archivesQuery = useQuery({
    queryKey: ["study-archives", { limit: 4 }],
    queryFn: () => studyArchivesApi.list({ limit: 4 }),
  });

  const recentTasksQuery = useQuery({
    queryKey: ["tasks", { type: "study_materials", limit: 8 }],
    queryFn: () => tasksApi.list({ type: "study_materials", limit: 8 }),
  });

  const recentTasks = useMemo(
    () =>
      (recentTasksQuery.data?.tasks ?? []).filter((task) =>
        ["study_materials", "study_material"].includes(task.task_type),
      ),
    [recentTasksQuery.data],
  );

  const latexMutation = useMutation({
    mutationFn: (payload: { markdown: string; topic?: string; subject?: string }) =>
      studyMaterialsApi.convertToLatex(payload),
    onSuccess: (result) => {
      setLatexUrl(result.tex_url);
      toast({ title: "LaTeX 已生成", description: result.filename, variant: "success" });
    },
    onError: (error) =>
      toast({ title: "LaTeX 转换失败", description: errorText(error), variant: "destructive" }),
  });

  const applyProjection = useCallback(
    (action: StudyMaterialsProjectionAction): StudyMaterialsProjection => {
      const next = studyMaterialsProjectionReducer(projectionRef.current, action);
      projectionRef.current = next;
      return next;
    },
    [],
  );

  const dispatchProjection = useCallback(
    (action: StudyMaterialsProjectionAction): StudyMaterialsProjection => {
      const next = applyProjection(action);
      setProjection(next);
      return next;
    },
    [applyProjection],
  );

  // 高频事件下节流持久化：全量回放时避免每事件一次同步 localStorage 写 + URL 更新。
  const lastPersistAtRef = useRef(0);
  const persistTask = useCallback(
    (taskId: string, lastSeq: number) => {
      const request = activeRequestRef.current;
      if (!request) return;
      const now = Date.now();
      if (now - lastPersistAtRef.current < 500) return;
      lastPersistAtRef.current = now;
      writePersistedRun({ ...request, taskId, lastSeq });
      setSearchParams({ task: taskId }, { replace: true });
    },
    [setSearchParams],
  );

  const processWireEvent = useCallback(
    (event: TaskEvent, opts: { render: boolean }) => {
      const decoded = decodeStudyMaterialsEvent(event);
      if (!decoded) return;

      const taskId =
        event.taskId ||
        (decoded.kind === "task_started" ? decoded.taskId : projectionRef.current.taskId);
      if (taskId) {
        const taskStore = useTasksStore.getState();
        taskStore.register(taskId, {
          type: "study_materials",
          title: activeRequestRef.current?.query || "学习资料",
        });
        // text_delta 在资料生成中是完整快照，不能送入追加语义的全局 store。
        if (event.type !== "text_delta") taskStore.applyEvent(taskId, event);
      }

      const next = applyProjection({
        type: "event",
        event: decoded,
        seq: event.seq,
        at: Date.now(),
      });
      if (opts.render) setProjection(next);

      if (next.taskId) persistTask(next.taskId, next.lastSeq);
      if (decoded.kind === "done") {
        clearPersistedRun();
        setResumeCandidate(null);
        void queryClient.invalidateQueries({ queryKey: ["study-archives"] });
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
    },
    [applyProjection, persistTask, queryClient],
  );

  const probeRecovery = useCallback(
    async (taskId: string) => {
      try {
        const status = await studyMaterialsApi.taskStatus(taskId);
        // 重连场景回填服务端检索覆盖，知识点看板仍有内容可显示（标注为服务端快照）。
        if (status.per_kp_state || status.search_summary_by_kp) {
          dispatchProjection({
            type: "hydrate_server_state",
            ...(status.per_kp_state ? { perKpState: status.per_kp_state } : {}),
            ...(status.search_summary_by_kp ? { searchSummaryByKp: status.search_summary_by_kp } : {}),
          });
        }
        if (status.status === "failed" && (status.resumable || status.recovery_available)) {
          dispatchProjection({
            type: "event",
            event: {
              kind: "recovery_available",
              recovery: {
                stage: status.last_failed_stage,
                recoverable: true,
              },
            },
            at: Date.now(),
          });
        }
      } catch {
        // 恢复探测失败不覆盖已收到的流错误。
      }
    },
    [dispatchProjection],
  );

  const settleStream = useCallback(
    (
      reason: StudyMaterialsStreamEndReason,
      error?: Error,
    ) => {
      setReceiving(false);
      abortRef.current = null;
      const next = dispatchProjection({
        type: "settled",
        reason,
        at: Date.now(),
        ...(error ? { error } : {}),
      });
      if ((next.runStatus === "failed" || next.runStatus === "interrupted") && next.taskId) {
        void probeRecovery(next.taskId);
      }
    },
    [dispatchProjection, probeRecovery],
  );

  // 事件合帧队列：重连全量回放可能瞬间涌入数千事件，逐事件 setState 会卡死主线程。
  // 先在 ref 中顺序应用 reducer，每帧只做一次渲染（live 事件最多延迟 32ms，无感）。
  const replayQueueRef = useRef<TaskEvent[]>([]);
  const replayFlushScheduledRef = useRef(false);

  const flushReplayQueue = useCallback(
    (epoch: number) => {
      replayFlushScheduledRef.current = false;
      const queue = replayQueueRef.current;
      replayQueueRef.current = [];
      if (!queue.length || epoch !== streamEpochRef.current) return;
      for (const event of queue) processWireEvent(event, { render: false });
      setProjection(projectionRef.current);
    },
    [processWireEvent],
  );

  const streamHandlers = useCallback(
    (controller: AbortController, epoch: number) => ({
      signal: controller.signal,
      onEvent: (event: TaskEvent) => {
        if (epoch !== streamEpochRef.current) return;
        replayQueueRef.current.push(event);
        if (!replayFlushScheduledRef.current) {
          replayFlushScheduledRef.current = true;
          setTimeout(() => flushReplayQueue(epoch), 32);
        }
      },
      onError: (error: Error) => {
        if (epoch !== streamEpochRef.current) return;
        toast({
          title: "资料生成连接异常",
          description: errorText(error),
          variant: "destructive" as const,
        });
      },
      onSettled: (termination: {
        reason: StudyMaterialsStreamEndReason;
        error?: Error;
      }) => {
        if (epoch !== streamEpochRef.current) return;
        // settle 前先排空队列，保证终态包含所有已接收事件。
        if (replayFlushScheduledRef.current || replayQueueRef.current.length) {
          flushReplayQueue(epoch);
        }
        settleStream(termination.reason, termination.error);
      },
    }),
    [flushReplayQueue, settleStream, toast],
  );

  /** 以完整请求启动生成；重试/重新生成复用同一入口，保证参数一致。 */
  const launchGeneration = useCallback(
    async (request: ActiveRequest) => {
      const query = request.query.trim();
      if (!query || receiving) return;

      streamEpochRef.current += 1;
      abortRef.current?.abort();
      const epoch = streamEpochRef.current;
      const nextRequest: ActiveRequest = { ...request, query };
      activeRequestRef.current = nextRequest;
      setActiveRequest(nextRequest);
      setDraft("");
      setInspectorToolId(null);
      setLatexUrl(undefined);
      setResumeCandidate(null);
      clearPersistedRun();
      setSearchParams({}, { replace: true });
      projectionRef.current = initialStudyMaterialsProjection();
      setProjection(projectionRef.current);

      const controller = new AbortController();
      abortRef.current = controller;
      setReceiving(true);
      setPinnedToBottom(true);
      setProcessCollapsed(false);
      setMobileTab("process");

      const payload: StudyGeneratePayload = {
        query,
        ...(nextRequest.subject ? { subject: nextRequest.subject } : {}),
        preset: nextRequest.preset,
        ...(nextRequest.requirements ? { requirements: nextRequest.requirements } : {}),
        ...nextRequest.flags,
        ...(nextRequest.maxPoints !== undefined ? { max_points: nextRequest.maxPoints } : {}),
      };
      await generateStudyMaterials(payload, streamHandlers(controller, epoch));
    },
    [receiving, setSearchParams, streamHandlers],
  );

  const startGeneration = useCallback(
    async (queryOverride?: string) => {
      const query = (queryOverride ?? draft).trim();
      if (!query) return;
      await launchGeneration({
        query,
        subject,
        preset,
        requirements: requirements.trim(),
        flags,
        ...(maxPoints !== undefined ? { maxPoints } : {}),
      });
    },
    [draft, flags, launchGeneration, maxPoints, preset, requirements, subject],
  );

  /** 「编辑并重跑」：把上次请求回填输入舱，由用户确认后再提交。 */
  const editPreviousRequest = useCallback(() => {
    const request = activeRequestRef.current;
    if (!request || receiving) return;
    setDraft(request.query);
    setSubject(request.subject);
    setPreset(request.preset);
    setRequirements(request.requirements);
    setFlags(request.flags);
    setMaxPoints(request.maxPoints);
  }, [receiving]);

  /** 同参重跑：早期失败重试与不可恢复失败的「重新生成」。 */
  const rerunActiveRequest = useCallback(() => {
    const request = activeRequestRef.current;
    if (request) void launchGeneration(request);
  }, [launchGeneration]);

  const continueWith = useCallback(
    async (
      mode:
        | "improve"
        | "deepen_research"
        | "resume_failed_stage"
        | "retry_search"
        | "replan_from_failure",
    ) => {
      const parentTaskId = projectionRef.current.taskId;
      if (!parentTaskId || receiving) return;

      streamEpochRef.current += 1;
      const epoch = streamEpochRef.current;
      const controller = new AbortController();
      abortRef.current = controller;
      setReceiving(true);
      setInspectorToolId(null);
      setLatexUrl(undefined);
      // 重置投影前把当前成果快照为「上一版」，改进期间下载入口不丢。
      dispatchProjection({ type: "begin_continuation" });
      await studyMaterialsApi.continueTask(
        parentTaskId,
        mode,
        streamHandlers(controller, epoch),
      );
    },
    [dispatchProjection, receiving, streamHandlers],
  );

  const resumeReceiving = useCallback(
    async (candidate?: ResumeCandidate) => {
      const target = candidate?.taskId ?? projectionRef.current.taskId;
      if (!target || receiving) return;

      streamEpochRef.current += 1;
      const epoch = streamEpochRef.current;
      const saved = candidate?.persisted ?? readPersistedRun();
      if (saved) {
        const request: ActiveRequest = {
          query: saved.query,
          subject: saved.subject,
          preset: saved.preset,
          requirements: saved.requirements,
          flags: saved.flags,
          ...(saved.maxPoints !== undefined ? { maxPoints: saved.maxPoints } : {}),
        };
        activeRequestRef.current = request;
        setActiveRequest(request);
      } else if (!activeRequestRef.current) {
        const request: ActiveRequest = {
          query: candidate?.query || "学习资料",
          subject: "",
          preset: "standard",
          requirements: "",
          flags: DEFAULT_FLAGS,
        };
        activeRequestRef.current = request;
        setActiveRequest(request);
      }

      const continuingSameTask = projectionRef.current.taskId === target;
      // 重新进入时投影为空，从 localStorage 持久化的进度续播，而不是从 0 全量回放。
      const afterSeq = resolveResumeAfterSeq({
        currentTaskId: projectionRef.current.taskId ?? null,
        currentLastSeq: projectionRef.current.lastSeq,
        targetTaskId: target,
        persistedLastSeq: saved?.lastSeq,
      });
      if (!continuingSameTask) {
        projectionRef.current = initialStudyMaterialsProjection();
        setProjection(projectionRef.current);
      }
      setResumeCandidate(null);
      const controller = new AbortController();
      abortRef.current = controller;
      setReceiving(true);
      setPinnedToBottom(true);
      await studyMaterialsApi.resumeTask(
        target,
        afterSeq,
        streamHandlers(controller, epoch),
      );
    },
    [receiving, streamHandlers],
  );

  const stopReceiving = useCallback(async () => {
    const taskId = projectionRef.current.taskId;
    dispatchProjection({ type: "stop_requested", at: Date.now() });
    if (taskId) {
      try {
        await tasksApi.cancel(taskId);
        dispatchProjection({ type: "server_cancel_confirmed", at: Date.now() });
      } catch {
        // 取消请求失败（离线等）也要中断本地接收，不能死路。
      }
    }
    abortRef.current?.abort();
  }, [dispatchProjection]);

  const reset = useCallback(() => {
    const activeTaskId =
      projectionRef.current.runStatus === "running" ? projectionRef.current.taskId : undefined;
    streamEpochRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setReceiving(false);
    setActiveRequest(null);
    activeRequestRef.current = null;
    projectionRef.current = initialStudyMaterialsProjection();
    setProjection(projectionRef.current);
    setInspectorToolId(null);
    setLatexUrl(undefined);
    setResumeCandidate(null);
    setProcessCollapsed(false);
    setMobileTab("process");
    clearPersistedRun();
    setSearchParams({}, { replace: true });
    // 「新的生成」与停止接收同理：尽力取消服务端任务，失败不阻塞本地重置。
    if (activeTaskId) {
      void tasksApi.cancel(activeTaskId).catch(() => {});
    }
  }, [setSearchParams]);

  const discardResume = useCallback(() => {
    setResumeCandidate(null);
    clearPersistedRun();
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  // 刷新后每个任务只探测一次。是否真正续播由用户确认，避免页面载入即占用长连接。
  useEffect(() => {
    const persisted = readPersistedRun();
    const taskId = searchParams.get("task") || persisted?.taskId;
    if (!taskId) {
      resumeProbeRef.current = "";
      return;
    }
    if (resumeProbeRef.current === taskId) return;
    resumeProbeRef.current = taskId;

    void (async () => {
      try {
        const status = await studyMaterialsApi.taskStatus(taskId);
        if (status.status === "running" || status.status === "failed") {
          setResumeCandidate({
            taskId,
            query: persisted?.query || status.query || "学习资料",
            status: status.status,
            ...(persisted ? { persisted } : {}),
          });
        } else if (status.status === "completed" && searchParams.get("task")) {
          setResumeCandidate({
            taskId,
            query: persisted?.query || status.query || "已完成的学习资料",
            status: "completed",
            ...(persisted ? { persisted } : {}),
          });
        } else {
          clearPersistedRun();
        }
      } catch {
        clearPersistedRun();
      }
    })();
  }, [searchParams]);

  useEffect(() => {
    if (!activeRequest && projection.runStatus === "idle") return;
    const element = scrollRef.current;
    if (element && pinnedToBottom) element.scrollTop = element.scrollHeight;
  }, [activeRequest, projection, pinnedToBottom]);

  const handleScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    setPinnedToBottom(element.scrollHeight - element.scrollTop - element.clientHeight < 80);
  };

  const scrollToLatest = () => {
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
    setPinnedToBottom(true);
  };

  const markdown = selectResultMarkdown(projection);
  const toolCount = selectToolCount(projection);
  const kpBoard = selectKnowledgePointBoard(projection);
  const todoList = useMemo(() => Object.values(projection.todos), [projection.todos]);
  // 有真实过程数据（todos 或泳道时间线）才切双栏；legacy 任务回放保持单栏推断视图。
  const hasProcessData = todoList.length > 0 || Object.keys(projection.traceByAgent).length > 0;
  const showProcess = Boolean(activeRequest) && hasProcessData;
  const hasConversation = activeRequest !== null || projection.runStatus !== "idle";
  const interruptedCandidate =
    projection.runStatus === "interrupted" && projection.taskId
      ? { taskId: projection.taskId, query: activeRequest?.query || "学习资料" }
      : null;
  // 知识点看板：运行中与中断后可见；done/failed 由结果卡与恢复卡接管。
  const showKpBoard =
    kpBoard.items.length > 0 &&
    (projection.runStatus === "running" || projection.runStatus === "interrupted");
  // 修订条只在审查/修订或检索补充期间出现，避免导出阶段残留过期提示。
  const showRevisionStrip =
    projection.runStatus === "running" &&
    (projection.researchRetry !== undefined ||
      (projection.revisionIssues.length > 0 &&
        (projection.currentStage === "review" || projection.currentStage === "research")));
  // task_started 之前的失败没有 taskId，恢复探测无从谈起，提供同参重试。
  const showEarlyRetry =
    Boolean(activeRequest) &&
    !projection.taskId &&
    (projection.runStatus === "failed" || projection.runStatus === "interrupted");
  const showRestorePrevious =
    Boolean(projection.previousResult) &&
    (projection.runStatus === "failed" || projection.runStatus === "interrupted");

  return (
    <div className="flex h-full min-h-0 animate-fade-in p-3 sm:p-4">
      <section className="flex min-w-0 flex-1 overflow-hidden rounded-2xl border border-border bg-card shadow-soft">
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
            <div className="flex min-w-0 items-center gap-2">
              <BookOpenText className="size-4 shrink-0 text-spectral" />
              <span className="truncate text-sm font-semibold">学习资料</span>
              <span className="hidden text-xs text-muted-foreground sm:inline">/ 对话式生成</span>
            </div>
            {hasConversation ? (
              <Button variant="ghost" size="sm" onClick={reset}>
                <Plus /> 新的生成
              </Button>
            ) : null}
          </header>

          <div className="relative min-h-0 flex-1">
            <div className="flex h-full min-h-0 flex-col lg:flex-row">
              {showProcess ? (
                <>
                  {/* 窄屏（<lg）：单栏 tabs（过程/文稿） */}
                  <div
                    role="tablist"
                    aria-label="过程与文稿切换"
                    className="flex shrink-0 items-center gap-1 border-b border-border px-3 py-2 lg:hidden"
                  >
                    {(["process", "document"] as const).map((tab) => (
                      <button
                        key={tab}
                        type="button"
                        role="tab"
                        aria-selected={mobileTab === tab}
                        onClick={() => setMobileTab(tab)}
                        className={cn(
                          "rounded-full px-3 py-1 text-xs transition-colors",
                          mobileTab === tab
                            ? "bg-surface font-medium text-foreground"
                            : "text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {tab === "process" ? "过程" : "文稿"}
                      </button>
                    ))}
                  </div>

                  {/* 左栏：过程面板（宽屏固定 420px，可折叠为细条；折叠只影响宽屏，窄屏仍走 tabs） */}
                  {processCollapsed ? (
                    <div className="hidden w-9 shrink-0 flex-col items-center border-r border-border py-2 lg:flex">
                      <button
                        type="button"
                        onClick={() => setProcessCollapsed(false)}
                        aria-label="展开过程面板"
                        className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-foreground"
                      >
                        <PanelLeftOpen className="size-4" />
                      </button>
                    </div>
                  ) : null}
                  <div
                    className={cn(
                      "min-h-0 flex-col",
                      mobileTab === "process" ? "flex" : "hidden",
                      processCollapsed
                        ? "lg:hidden"
                        : "lg:flex lg:w-[420px] lg:shrink-0 lg:border-r lg:border-border",
                    )}
                  >
                    <ProcessPanel
                      todos={todoList}
                      traceByAgent={projection.traceByAgent}
                      sectionStatus={projection.sectionStatus}
                      onCollapse={() => setProcessCollapsed(true)}
                      className="min-h-0 flex-1"
                    />
                  </div>
                </>
              ) : null}

              {/* 右栏文稿预览：窄屏按 tab 显隐，宽屏常驻 */}
              <div
                className={cn(
                  "min-h-0 min-w-0 flex-1",
                  showProcess && mobileTab !== "document" ? "hidden lg:block" : "flex flex-col",
                )}
              >
                <div
                  ref={scrollRef}
                  onScroll={handleScroll}
                  className="h-full overflow-y-auto px-4 py-4"
                >
              <div className="mx-auto max-w-[800px]">
                {resumeCandidate ? (
                  <div className="mb-5">
                    <ResumeBanner
                      title={resumeCandidate.query}
                      status={resumeCandidate.status}
                      onResume={() => void resumeReceiving(resumeCandidate)}
                      onDiscard={discardResume}
                      busy={receiving}
                    />
                  </div>
                ) : null}

                {!hasConversation ? (
                  <MaterialsWelcome
                    preset={preset}
                    onPresetChange={setPreset}
                    onExample={setDraft}
                    archives={archivesQuery.data?.items ?? []}
                    archivesPending={archivesQuery.isPending}
                    recentTasks={recentTasks}
                  />
                ) : activeRequest ? (
                  <div className="space-y-6 pb-4">
                    <StudyMaterialsUserRequest
                      query={activeRequest.query}
                      subject={activeRequest.subject}
                      preset={activeRequest.preset}
                      requirements={activeRequest.requirements}
                      withQuestions={activeRequest.flags.with_questions}
                      withDiagrams={activeRequest.flags.with_diagrams}
                      extraTools={activeRequest.flags.enable_extra_tools}
                      preferLocalArchive={activeRequest.flags.prefer_local_archive}
                      {...(activeRequest.maxPoints !== undefined
                        ? { maxPoints: activeRequest.maxPoints }
                        : {})}
                      onEditRerun={receiving ? undefined : editPreviousRequest}
                    />

                    <AssistantShell>
                      <div className="space-y-4">
                        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                          {receiving ? <Spinner /> : projection.runStatus === "done" ? <CheckCircle2 className="size-4 text-tool-success" /> : <Sparkles className="size-4 text-spectral" />}
                          <span>{projection.statusText || "正在启动资料生成任务…"}</span>
                          {projection.currentStage ? (
                            <span className="text-xs">
                              · {selectStageSummary(projection)}
                              {toolCount > 0 ? ` · ${toolCount} 个工具调用` : ""}
                            </span>
                          ) : null}
                        </div>

                        <div className="overflow-x-auto pb-1">
                          <StageProgress stages={projection.stages} progress={projection.progress} />
                        </div>

                        {/* 有 todos 数据时优先展示真实清单进度；没有时保持现有推断步进器。 */}
                        <StudyTodoProgress todos={todoList} />

                        {projection.previousResult ? (
                          <MaterialResultCard
                            compact
                            result={projection.previousResult.result}
                            markdown={projection.previousResult.markdownSnapshot}
                            preset={activeRequest.preset}
                          />
                        ) : null}

                        {showKpBoard ? (
                          <KnowledgePointBoard
                            board={kpBoard}
                            onInspect={(tool: ToolStepView) => setInspectorToolId(tool.id)}
                          />
                        ) : null}

                        {showRevisionStrip ? (
                          <RevisionStrip
                            issues={projection.revisionIssues}
                            {...(projection.remainingRevisionAttempts !== undefined
                              ? { remainingAttempts: projection.remainingRevisionAttempts }
                              : {})}
                            {...(projection.researchRetry
                              ? { researchRetry: projection.researchRetry }
                              : {})}
                          />
                        ) : null}

                        <AssistantTurn
                          turn={projection.turn}
                          current
                          onInspectTool={(tool: ToolStepView) => setInspectorToolId(tool.id)}
                        />

                        {projection.runStatus === "running" && !projection.markdownSnapshot ? (
                          <p className="text-xs leading-5 text-muted-foreground">
                            legacy 生成流不会发送实时 Markdown 正文；最终讲义将在完成事件到达后显示。
                          </p>
                        ) : null}

                        {projection.runStatus === "running" && projection.markdownSnapshot ? (
                          <DraftPreviewPane
                            markdown={projection.markdownSnapshot}
                            version={projection.snapshotVersion}
                          />
                        ) : null}

                        {projection.runStatus === "done" && projection.result ? (
                          <>
                            <MaterialResultCard
                              result={projection.result}
                              markdown={markdown}
                              preset={activeRequest.preset}
                              latexUrl={latexUrl}
                              convertingLatex={latexMutation.isPending}
                              onConvertLatex={() => {
                                if (!markdown) return;
                                latexMutation.mutate({
                                  markdown,
                                  topic: projection.result?.material?.topic || activeRequest.query,
                                  subject: projection.result?.material?.subject || activeRequest.subject,
                                });
                              }}
                            />
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-xs text-muted-foreground">接下来可以</span>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void continueWith("improve")}
                                disabled={receiving}
                              >
                                <Sparkles /> 继续迭代优化
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void continueWith("deepen_research")}
                                disabled={receiving}
                              >
                                <Sparkles /> 加深研究
                              </Button>
                            </div>
                          </>
                        ) : null}

                        {showRestorePrevious ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() =>
                                dispatchProjection({ type: "restore_previous_result", at: Date.now() })
                              }
                              disabled={receiving}
                            >
                              <Undo2 /> 还原上一版
                            </Button>
                            <span className="text-xs text-muted-foreground">
                              本轮未产出新成果，可以切回上一版继续下载。
                            </span>
                          </div>
                        ) : null}

                        {showEarlyRetry ? (
                          <EarlyRetryNotice onRetry={rerunActiveRequest} disabled={receiving} />
                        ) : null}

                        {projection.runStatus === "failed" && projection.taskId ? (
                          <RecoveryCard
                            message={projection.turn.errorMessage || projection.statusText || "生成任务失败"}
                            recovery={projection.recovery}
                            onContinue={(mode) => void continueWith(mode)}
                            onRegenerate={rerunActiveRequest}
                            disabled={receiving}
                          />
                        ) : null}

                        {interruptedCandidate ? (
                          projection.serverCancelConfirmed ? (
                            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 shadow-soft">
                              <p className="min-w-0 flex-1 text-xs leading-5 text-muted-foreground">
                                任务已在服务端取消，无法继续接收。可以基于已保留的中间成果继续生成。
                              </p>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void continueWith("improve")}
                                disabled={receiving}
                              >
                                <Sparkles /> 继续生成
                              </Button>
                            </div>
                          ) : (
                            <ResumeBanner
                              title={interruptedCandidate.query}
                              onResume={() => void resumeReceiving(interruptedCandidate)}
                              onDiscard={reset}
                              busy={receiving}
                            />
                          )
                        ) : null}
                      </div>
                    </AssistantShell>
                  </div>
                ) : null}
              </div>
                </div>
              </div>
            </div>

            {!pinnedToBottom && (!showProcess || mobileTab === "document") ? (
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
            <PromptComposer
              className="mx-auto max-w-[880px]"
              value={draft}
              onChange={setDraft}
              onSubmit={() => void startGeneration()}
              sending={receiving}
              onStop={() => void stopReceiving()}
              submitLabel="开始生成"
              placeholder={
                projection.runStatus === "done"
                  ? "输入另一个主题，开始一份新的讲义"
                  : "例如：函数单调性；也可以补充「偏高考难度，多配例题」这样的要求"
              }
              autoFocus
              leftSlot={
                <>
                  <SubjectSelect
                    value={subject}
                    onValueChange={setSubject}
                    placeholder="学科"
                    className="w-36"
                  />
                  <Select value={preset} onValueChange={(value) => setPreset(value as StudyPreset)}>
                    <SelectTrigger className="h-8 w-28">
                      <SelectValue placeholder="预设" />
                    </SelectTrigger>
                    <SelectContent>
                      {STUDY_PRESETS.map((item) => (
                        <SelectItem key={item.value} value={item.value}>
                          {item.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <GenerationOptions
                    requirements={requirements}
                    onRequirementsChange={setRequirements}
                    flags={flags}
                    onFlagsChange={setFlags}
                    maxPoints={maxPoints}
                    onMaxPointsChange={setMaxPoints}
                  />
                </>
              }
            />
            <div className="mx-auto mt-1.5 flex max-w-[880px] items-center gap-2 px-1 text-[11px] text-muted-foreground">
              <History className="size-3" />
              Enter 发送 · Shift+Enter 换行 · 内容由 AI 生成，仅供参考
            </div>
          </div>
        </div>

        {inspectorToolId ? (
          <ToolInspectorHost
            turn={projection.turn}
            selectedToolId={inspectorToolId}
            onSelectTool={setInspectorToolId}
            onClose={() => setInspectorToolId(null)}
          />
        ) : null}
      </section>
    </div>
  );
}
