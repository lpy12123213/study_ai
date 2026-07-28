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
  History,
  Plus,
  SlidersHorizontal,
  Sparkles,
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
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
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
  selectResultMarkdown,
  selectStageSummary,
  selectToolCount,
} from "./model/selectors";
import type { StudyMaterialsProjection } from "./model/types";
import { decodeStudyMaterialsEvent } from "./streaming/contract";
import { MaterialResultCard } from "./ui/material-result-card";
import { MaterialsWelcome } from "./ui/materials-welcome";
import { RecoveryCard } from "./ui/recovery-card";
import { ResumeBanner } from "./ui/resume-banner";
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
}

interface PersistedRun extends ActiveRequest {
  taskId: string;
  lastSeq: number;
}

interface ResumeCandidate {
  taskId: string;
  query: string;
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
}: {
  requirements: string;
  onRequirementsChange: (value: string) => void;
  flags: GenerationFlags;
  onFlagsChange: (flags: GenerationFlags) => void;
}) {
  const selected = Object.values(flags).filter(Boolean).length;
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
  const [activeRequest, setActiveRequest] = useState<ActiveRequest | null>(null);
  const [projection, setProjection] = useState<StudyMaterialsProjection>(
    initialStudyMaterialsProjection,
  );
  const [receiving, setReceiving] = useState(false);
  const [resumeCandidate, setResumeCandidate] = useState<ResumeCandidate | null>(null);
  const [inspectorToolId, setInspectorToolId] = useState<string | null>(null);
  const [latexUrl, setLatexUrl] = useState<string | undefined>();
  const [pinnedToBottom, setPinnedToBottom] = useState(true);

  const projectionRef = useRef(projection);
  const activeRequestRef = useRef(activeRequest);
  const abortRef = useRef<AbortController | null>(null);
  const streamEpochRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const resumeProbeRef = useRef(false);

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

  const dispatchProjection = useCallback(
    (action: StudyMaterialsProjectionAction): StudyMaterialsProjection => {
      const next = studyMaterialsProjectionReducer(projectionRef.current, action);
      projectionRef.current = next;
      setProjection(next);
      return next;
    },
    [],
  );

  const persistTask = useCallback(
    (taskId: string, lastSeq: number) => {
      const request = activeRequestRef.current;
      if (!request) return;
      writePersistedRun({ ...request, taskId, lastSeq });
      setSearchParams({ task: taskId }, { replace: true });
    },
    [setSearchParams],
  );

  const handleWireEvent = useCallback(
    (event: TaskEvent) => {
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

      const next = dispatchProjection({
        type: "event",
        event: decoded,
        seq: event.seq,
        at: Date.now(),
      });

      if (next.taskId) persistTask(next.taskId, next.lastSeq);
      if (decoded.kind === "done") {
        clearPersistedRun();
        setResumeCandidate(null);
        void queryClient.invalidateQueries({ queryKey: ["study-archives"] });
        void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      }
    },
    [dispatchProjection, persistTask, queryClient],
  );

  const probeRecovery = useCallback(
    async (taskId: string) => {
      try {
        const status = await studyMaterialsApi.taskStatus(taskId);
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

  const streamHandlers = useCallback(
    (controller: AbortController, epoch: number) => ({
      signal: controller.signal,
      onEvent: (event: TaskEvent) => {
        if (epoch === streamEpochRef.current) handleWireEvent(event);
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
        if (epoch === streamEpochRef.current) {
          settleStream(termination.reason, termination.error);
        }
      },
    }),
    [handleWireEvent, settleStream, toast],
  );

  const startGeneration = useCallback(
    async (queryOverride?: string) => {
      const query = (queryOverride ?? draft).trim();
      if (!query || receiving) return;

      streamEpochRef.current += 1;
      abortRef.current?.abort();
      const epoch = streamEpochRef.current;
      const request: ActiveRequest = {
        query,
        subject,
        preset,
        requirements: requirements.trim(),
        flags,
      };
      activeRequestRef.current = request;
      setActiveRequest(request);
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

      const payload: StudyGeneratePayload = {
        query,
        ...(subject ? { subject } : {}),
        preset,
        ...(request.requirements ? { requirements: request.requirements } : {}),
        ...flags,
      };
      await generateStudyMaterials(payload, streamHandlers(controller, epoch));
    },
    [
      draft,
      flags,
      preset,
      receiving,
      requirements,
      setSearchParams,
      streamHandlers,
      subject,
    ],
  );

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
      projectionRef.current = initialStudyMaterialsProjection();
      setProjection(projectionRef.current);
      await studyMaterialsApi.continueTask(
        parentTaskId,
        mode,
        streamHandlers(controller, epoch),
      );
    },
    [receiving, streamHandlers],
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
      const afterSeq = continuingSameTask ? projectionRef.current.lastSeq : 0;
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

  const stopReceiving = useCallback(() => {
    dispatchProjection({ type: "stop_requested", at: Date.now() });
    abortRef.current?.abort();
  }, [dispatchProjection]);

  const reset = useCallback(() => {
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
    clearPersistedRun();
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  const discardResume = useCallback(() => {
    setResumeCandidate(null);
    clearPersistedRun();
    setSearchParams({}, { replace: true });
  }, [setSearchParams]);

  // 刷新后只探测一次。是否真正续播由用户确认，避免页面载入即占用长连接。
  useEffect(() => {
    if (resumeProbeRef.current) return;
    resumeProbeRef.current = true;
    const persisted = readPersistedRun();
    const taskId = searchParams.get("task") || persisted?.taskId;
    if (!taskId) return;

    void (async () => {
      try {
        const status = await studyMaterialsApi.taskStatus(taskId);
        if (status.status === "running" || status.status === "failed") {
          setResumeCandidate({
            taskId,
            query: persisted?.query || status.query || "学习资料",
            ...(persisted ? { persisted } : {}),
          });
        } else if (status.status === "completed" && searchParams.get("task")) {
          setResumeCandidate({
            taskId,
            query: persisted?.query || status.query || "已完成的学习资料",
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
  const hasConversation = activeRequest !== null || projection.runStatus !== "idle";
  const interruptedCandidate =
    projection.runStatus === "interrupted" && projection.taskId
      ? { taskId: projection.taskId, query: activeRequest?.query || "学习资料" }
      : null;

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
                      withQuestions={activeRequest.flags.with_questions}
                      withDiagrams={activeRequest.flags.with_diagrams}
                      extraTools={activeRequest.flags.enable_extra_tools}
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
                          <StageProgress stages={projection.stages} />
                        </div>

                        <AssistantTurn
                          turn={projection.turn}
                          current
                          onInspectTool={(tool: ToolStepView) => setInspectorToolId(tool.id)}
                        />

                        {projection.runStatus === "running" ? (
                          <p className="text-xs leading-5 text-muted-foreground">
                            legacy 生成流不会发送实时 Markdown 正文；最终讲义将在完成事件到达后显示。
                          </p>
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

                        {projection.runStatus === "failed" ? (
                          <RecoveryCard
                            message={projection.turn.errorMessage || projection.statusText || "生成任务失败"}
                            recovery={projection.recovery}
                            onContinue={(mode) => void continueWith(mode)}
                            disabled={receiving}
                          />
                        ) : null}

                        {interruptedCandidate ? (
                          <ResumeBanner
                            title={interruptedCandidate.query}
                            onResume={() => void resumeReceiving(interruptedCandidate)}
                            onDiscard={reset}
                            busy={receiving}
                          />
                        ) : null}
                      </div>
                    </AssistantShell>
                  </div>
                ) : null}
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
            <PromptComposer
              className="mx-auto max-w-[880px]"
              value={draft}
              onChange={setDraft}
              onSubmit={() => void startGeneration()}
              sending={receiving}
              onStop={stopReceiving}
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
