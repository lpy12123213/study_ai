import { useEffect, useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, ClipboardCheck, RotateCcw, Search, Trash2 } from "lucide-react";
import { ApiError } from "@/shared/api/http-client";
import { tasksApi } from "@/features/task-center/api";
import type { ComposeDraft, ComposeDraftQuestion } from "@/shared/api/types";
import { TASK_STATUS_LABELS } from "@/shared/api/types";
import type { ActiveTask } from "@/stores/tasks";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/utils";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { QuestionCard } from "@/components/question/question-card";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";
import { errMsg, draftQuestionId, extractComposeDraft } from "../model/utils";
import { ComposeResultCard } from "./compose-result-card";


// ---------------- 页签 3：人工审核 ----------------

export function DraftReview({ task }: { task: ActiveTask }) {
  const toast = useUiStore((s) => s.toast);
  const draft = (task.composeDraft ?? {}) as ComposeDraft;
  const questions: ComposeDraftQuestion[] = Array.isArray(draft.questions) ? draft.questions : [];

  const [rejected, setRejected] = useState<ReadonlySet<string>>(new Set());
  const [paperName, setPaperName] = useState(String(draft.paperName ?? ""));
  const [runnerUnavailable, setRunnerUnavailable] = useState(false);

  const result = task.result;

  const toggleReject = (qid: string) =>
    setRejected((prev) => {
      const next = new Set(prev);
      if (next.has(qid)) next.delete(qid);
      else next.add(qid);
      return next;
    });

  const reviewMut = useMutation({
    mutationFn: () =>
      tasksApi.composeReview(task.taskId, {
        paperName: paperName.trim() || undefined,
        paperId: typeof draft.paperId === "number" ? (draft.paperId as number) : undefined,
        questions: questions.map((q) => {
          const qid = draftQuestionId(q);
          const base: Record<string, any> = { ...q, questionId: qid, question_id: qid };
          if (rejected.has(qid)) {
            base.reviewAction = "reject";
            base.reviewStatus = "reject";
          }
          return base;
        }),
      }),
    onSuccess: (resp) => {
      const store = useTasksStore.getState();
      if (resp?.paper) store.applyEvent(task.taskId, { type: "result", data: { result: resp.paper }, seq: 0 });
      store.watch(task.taskId);
      toast({
        title: "审核已提交",
        description: `通过 ${resp?.review?.approved ?? "—"} 题，剔除 ${resp?.review?.rejected ?? "—"} 题`,
        variant: "success",
      });
    },
    onError: (err) => {
      if (err instanceof ApiError && (err.status === 409 || err.code === "task_runner_unavailable")) {
        setRunnerUnavailable(true);
        return;
      }
      if (err instanceof ApiError && err.code === "task_not_pending_review") {
        toast({
          title: "任务已不在待审核状态",
          description: "该任务可能已被审核或已结束，请刷新任务状态后再试",
          variant: "warning",
        });
        return;
      }
      toast({ title: "提交审核失败", description: errMsg(err), variant: "destructive" });
    },
  });

  const submit = () => {
    if (questions.length === 0) return;
    if (rejected.size >= questions.length) {
      toast({ title: "无法提交", description: "不能剔除全部题目，至少保留一题", variant: "warning" });
      return;
    }
    setRunnerUnavailable(false);
    reviewMut.mutate();
  };

  if (result) {
    return <ComposeResultCard result={result} />;
  }

  return (
    <div className="space-y-4">
      {runnerUnavailable ? (
        <Alert variant="warning">
          <AlertTriangle />
          <AlertTitle>任务运行器不可用</AlertTitle>
          <AlertDescription>任务运行器不可用，请到任务中心重试（retry）后再回来提交审核。</AlertDescription>
        </Alert>
      ) : null}

      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="review-paper-name">试卷名称</Label>
            <Input id="review-paper-name" value={paperName} onChange={(e) => setPaperName(e.target.value)} />
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground tabular-nums">
              保留 {questions.length - rejected.size} / {questions.length} 题
            </span>
            <Button onClick={submit} disabled={reviewMut.isPending || questions.length === 0}>
              {reviewMut.isPending ? <Spinner className="text-primary-foreground" /> : <CheckCircle2 />}
              提交审核
            </Button>
          </div>
        </CardContent>
      </Card>

      {reviewMut.isSuccess ? <TaskProgressPanel taskId={task.taskId} /> : null}

      <div className="space-y-3">
        {questions.map((q, idx) => {
          const qid = draftQuestionId(q) || `idx-${idx}`;
          const isRejected = rejected.has(qid);
          return (
            <QuestionCard
              key={qid}
              className={cn("transition", isRejected && "opacity-50 grayscale")}
              question={{
                question_id: draftQuestionId(q),
                stem: q.stem,
                answer: q.answer,
                analysis: q.analysis,
                type: q.type,
                difficulty: q.difficulty,
                knowledge_point: q.knowledgePoint ?? q.knowledge_point,
                source_url: q.sourceUrl ?? q.source_url,
              }}
              actions={
                <Button size="sm" variant={isRejected ? "outline" : "secondary"} onClick={() => toggleReject(qid)}>
                  {isRejected ? <RotateCcw /> : <Trash2 />}
                  {isRejected ? "恢复保留" : "剔除"}
                </Button>
              }
            />
          );
        })}
      </div>
    </div>
  );
}

export function ReviewTab({ focusTaskId }: { focusTaskId: string | null }) {
  const toast = useUiStore((s) => s.toast);
  const active = useTasksStore((s) => s.active);
  const reviewTasks = useMemo(
    () => Object.values(active).filter((t) => t.status === "pending_review" && t.composeDraft),
    [active],
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [manualId, setManualId] = useState("");

  useEffect(() => {
    if (focusTaskId) setSelectedId(focusTaskId);
  }, [focusTaskId]);

  const currentId =
    selectedId && reviewTasks.some((t) => t.taskId === selectedId) ? selectedId : (reviewTasks[0]?.taskId ?? null);
  const currentTask = currentId ? active[currentId] : undefined;

  const loadMut = useMutation({
    mutationFn: (taskId: string) => tasksApi.get(taskId, { includeEvents: true, eventsLimit: 5000 }),
    onSuccess: (detail, taskId) => {
      // 仅 pending_review 状态可进入审核；已完成/失败的任务提交时必然后端 400 task_not_pending_review
      const status = String(detail.status ?? "");
      if (status && status !== "pending_review") {
        toast({
          title: "该任务不在待审核状态",
          description: `当前状态：${TASK_STATUS_LABELS[status] ?? status}，仅待审核的组卷任务可加载`,
          variant: "warning",
        });
        return;
      }
      const draft = extractComposeDraft(detail);
      if (!draft) {
        toast({ title: "未找到组卷草稿", description: "该任务没有可审核的 composeDraft", variant: "warning" });
        return;
      }
      const store = useTasksStore.getState();
      store.register(taskId, {
        type: "paper_compose",
        title: String(detail.title ?? draft.paperName ?? "组卷审核"),
      });
      store.applyEvent(taskId, { type: "pending_review", data: { composeDraft: draft }, seq: 0 });
      setSelectedId(taskId);
      toast({ title: "草稿已加载", variant: "success" });
    },
    onError: (err) => toast({ title: "加载任务失败", description: errMsg(err), variant: "destructive" }),
  });

  const loadManual = () => {
    const id = manualId.trim();
    if (!id) {
      toast({ title: "请输入任务 ID", variant: "warning" });
      return;
    }
    loadMut.mutate(id);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-end">
          <div className="flex-1 space-y-1.5">
            <Label htmlFor="review-task-id">按任务 ID 加载草稿</Label>
            <Input
              id="review-task-id"
              value={manualId}
              onChange={(e) => setManualId(e.target.value)}
              placeholder="例如：compose-xxxxxxxxxxxx"
              onKeyDown={(e) => {
                if (e.key === "Enter") loadManual();
              }}
            />
          </div>
          <Button variant="outline" onClick={loadManual} disabled={loadMut.isPending}>
            {loadMut.isPending ? <Spinner /> : <Search />}
            加载
          </Button>
        </CardContent>
      </Card>

      {reviewTasks.length > 1 ? (
        <div className="space-y-1.5">
          <Label>选择待审核任务</Label>
          <Select value={currentId ?? ""} onValueChange={setSelectedId}>
            <SelectTrigger className="w-full sm:w-96">
              <SelectValue placeholder="选择待审核任务" />
            </SelectTrigger>
            <SelectContent>
              {reviewTasks.map((t) => (
                <SelectItem key={t.taskId} value={t.taskId}>
                  {t.title || t.taskId}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      ) : null}

      {currentTask ? (
        <DraftReview key={currentTask.taskId} task={currentTask} />
      ) : (
        <EmptyState
          icon={ClipboardCheck}
          title="暂无待审核的组卷任务"
          description="蓝图组卷开启「人工审核」后，草稿会出现在这里；也可以在上方手动输入任务 ID 加载。"
        />
      )}
    </div>
  );
}

