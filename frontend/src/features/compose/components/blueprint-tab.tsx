import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, Layers, Plus, Square, Trash2 } from "lucide-react";
import { blueprintsApi, composePaper } from "@/features/paper-compose/api";
import type { Blueprint, BlueprintSlot } from "@/shared/api/types";
import { DEFAULT_SUBJECT } from "@/shared/api/types";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { SubjectSelect } from "@/components/question/subject-select";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";
import { errMsg } from "../model/utils";
import { SlotsEditor } from "./slots-editor";
import { validSlots } from "./slots-editor";
import { OptionSwitch } from "./option-controls";
import { OptionNumber } from "./option-controls";
import { ComposeResultCard } from "./compose-result-card";


// ---------------- 页签 2：蓝图组卷 ----------------

interface BlueprintFormState {
  name: string;
  subject: string;
  topic: string;
  slots: BlueprintSlot[];
}

export function BlueprintTab({ onGotoReview }: { onGotoReview: (taskId: string) => void }) {
  const toast = useUiStore((s) => s.toast);
  const queryClient = useQueryClient();

  const blueprintsQuery = useQuery({ queryKey: ["blueprints"], queryFn: () => blueprintsApi.list() });
  const blueprints = blueprintsQuery.data ?? [];

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleting, setDeleting] = useState<Blueprint | null>(null);
  const [bpForm, setBpForm] = useState<BlueprintFormState>({
    name: "",
    subject: DEFAULT_SUBJECT,
    topic: "",
    slots: [{ questionType: "单选题", count: 5, difficulty: "中等" }],
  });

  const [manualSubject, setManualSubject] = useState<string>(DEFAULT_SUBJECT);
  const [manualTopic, setManualTopic] = useState("");
  const [manualSlots, setManualSlots] = useState<BlueprintSlot[]>([
    { questionType: "单选题", count: 5, difficulty: "中等" },
    { questionType: "填空题", count: 3, difficulty: "中等" },
  ]);

  const [paperName, setPaperName] = useState("");
  const [paperNameTouched, setPaperNameTouched] = useState(false);

  const [requireHumanReview, setRequireHumanReview] = useState(true);
  const [autoAiBackfill, setAutoAiBackfill] = useState(true);
  const [avoidUsed, setAvoidUsed] = useState(true);
  const [dedupByStem, setDedupByStem] = useState(true);
  const [maxPages, setMaxPages] = useState(2);
  const [minQualityScore, setMinQualityScore] = useState(60);
  const [judgePassScore, setJudgePassScore] = useState(65);

  const [composeTaskId, setComposeTaskId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const task = useTasksStore((s) => (composeTaskId ? s.active[composeTaskId] : undefined));

  const selectedBp = selectedId ? (blueprints.find((b) => b.id === selectedId) ?? null) : null;
  const effectiveSubject = selectedBp?.subject ?? manualSubject;
  const effectiveTopic = selectedBp?.topic ?? manualTopic;
  const effectiveSlots: BlueprintSlot[] = selectedBp?.slots ?? manualSlots;

  useEffect(() => {
    if (!paperNameTouched) {
      setPaperName(`${effectiveSubject}组卷 ${formatDate(new Date().toISOString())}`);
    }
  }, [effectiveSubject, paperNameTouched]);

  const createMut = useMutation({
    mutationFn: (form: BlueprintFormState) =>
      blueprintsApi.create({
        name: form.name.trim(),
        subject: form.subject,
        topic: form.topic.trim() || undefined,
        slots: validSlots(form.slots),
      }),
    onSuccess: () => {
      toast({ title: "蓝图已保存", variant: "success" });
      setCreateOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["blueprints"] });
    },
    onError: (err) => toast({ title: "保存蓝图失败", description: errMsg(err), variant: "destructive" }),
  });

  const removeMut = useMutation({
    mutationFn: (id: string) => blueprintsApi.remove(id),
    onSuccess: (_data, id) => {
      toast({ title: "蓝图已删除", variant: "success" });
      setDeleting(null);
      if (selectedId === id) setSelectedId(null);
      void queryClient.invalidateQueries({ queryKey: ["blueprints"] });
    },
    onError: (err) => toast({ title: "删除蓝图失败", description: errMsg(err), variant: "destructive" }),
  });

  const openCreateDialog = () => {
    setBpForm({
      name: "",
      subject: DEFAULT_SUBJECT,
      topic: "",
      slots: [{ questionType: "单选题", count: 5, difficulty: "中等" }],
    });
    setCreateOpen(true);
  };

  const submitBlueprint = () => {
    if (!bpForm.name.trim()) {
      toast({ title: "请输入蓝图名称", variant: "warning" });
      return;
    }
    if (validSlots(bpForm.slots).length === 0) {
      toast({ title: "请至少配置一个有效槽位", description: "每行需选择题型且数量大于 0", variant: "warning" });
      return;
    }
    createMut.mutate(bpForm);
  };

  const startCompose = () => {
    const slots = validSlots(effectiveSlots);
    if (slots.length === 0) {
      toast({ title: "请至少配置一个题型槽位", variant: "warning" });
      return;
    }
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setComposeTaskId(null);
    setRunning(true);
    let registered = false;
    void composePaper(
      {
        subject: effectiveSubject,
        topic: effectiveTopic || undefined,
        paperName: paperName.trim() || undefined,
        slots,
        options: {
          requireHumanReview,
          autoAiBackfill,
          avoidUsed,
          dedupByStem,
          maxPages,
          minQualityScore,
          judgePassScore,
        },
      },
      {
        signal: ctrl.signal,
        onEvent: (ev) => {
          const store = useTasksStore.getState();
          if (!registered && ev.taskId) {
            registered = true;
            setComposeTaskId(ev.taskId);
            store.register(ev.taskId, { type: "paper_compose", title: paperName.trim() || "蓝图组卷" });
          }
          if (ev.taskId) store.applyEvent(ev.taskId, ev);
        },
        onDone: () => setRunning(false),
        onError: (err) => {
          setRunning(false);
          toast({ title: "组卷失败", description: errMsg(err), variant: "destructive" });
        },
      },
    );
  };

  const stopCompose = () => {
    abortRef.current?.abort();
    setRunning(false);
  };

  const pendingReview = task?.status === "pending_review" && !task.result;

  return (
    <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[320px_1fr]">
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>组卷蓝图</CardTitle>
            <CardDescription>可复用的题型配比方案</CardDescription>
          </div>
          <Button size="sm" variant="outline" onClick={openCreateDialog}>
            <Plus /> 新建
          </Button>
        </CardHeader>
        <CardContent className="space-y-2">
          <div
            role="button"
            tabIndex={0}
            onClick={() => setSelectedId(null)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") setSelectedId(null);
            }}
            className={cn(
              "w-full cursor-pointer rounded-lg border p-3 text-left transition-colors",
              selectedId === null ? "border-primary bg-accent/60 ring-1 ring-primary/40" : "border-border hover:bg-accent/40",
            )}
          >
            <div className="text-sm font-medium">手工配置</div>
            <div className="mt-0.5 text-xs text-muted-foreground">不使用蓝图，直接在右侧编辑槽位</div>
          </div>

          {blueprintsQuery.isPending ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-16 w-full rounded-lg" />
              ))}
            </div>
          ) : null}

          {blueprintsQuery.isError ? (
            <Alert variant="destructive">
              <AlertTriangle />
              <AlertDescription>蓝图列表加载失败，请稍后重试</AlertDescription>
            </Alert>
          ) : null}

          {blueprints.map((bp) => {
            const active = bp.id === selectedId;
            return (
              <div
                key={bp.id}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedId(active ? null : bp.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") setSelectedId(active ? null : bp.id);
                }}
                className={cn(
                  "group w-full cursor-pointer rounded-lg border p-3 text-left transition-colors",
                  active ? "border-primary bg-accent/60 ring-1 ring-primary/40" : "border-border hover:bg-accent/40",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{bp.name}</span>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    className="shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 hover:text-destructive"
                    onClick={(e) => {
                      e.stopPropagation();
                      setDeleting(bp);
                    }}
                    aria-label={`删除蓝图 ${bp.name}`}
                  >
                    <Trash2 />
                  </Button>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  <Badge variant="secondary">{bp.subject}</Badge>
                  {bp.topic ? <span>{bp.topic}</span> : null}
                </div>
                <div className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                  {bp.slots.map((s) => `${s.questionType}×${s.count}${s.difficulty ? `·${s.difficulty}` : ""}`).join("，") || "无槽位"}
                </div>
              </div>
            );
          })}

          {!blueprintsQuery.isPending && !blueprintsQuery.isError && blueprints.length === 0 ? (
            <p className="py-2 text-center text-xs text-muted-foreground">还没有蓝图，点击右上角「新建」创建</p>
          ) : null}
        </CardContent>
      </Card>

      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>组卷配置</CardTitle>
            <CardDescription>
              {selectedBp ? `使用蓝图「${selectedBp.name}」` : "手工配置槽位"}
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {selectedBp ? (
              <div className="rounded-lg bg-muted/60 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">{selectedBp.subject}</Badge>
                  {selectedBp.topic ? <span className="text-muted-foreground">{selectedBp.topic}</span> : null}
                </div>
                <div className="mt-1.5 text-xs text-muted-foreground">
                  {selectedBp.slots.map((s) => `${s.questionType}×${s.count}${s.difficulty ? `·${s.difficulty}` : ""}`).join("，")}
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label>学科</Label>
                  <SubjectSelect value={manualSubject} onValueChange={setManualSubject} />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="manual-topic">主题 / 知识点</Label>
                  <Input
                    id="manual-topic"
                    value={manualTopic}
                    onChange={(e) => setManualTopic(e.target.value)}
                    placeholder="例如：三角函数"
                  />
                </div>
                <div className="space-y-1.5 sm:col-span-2">
                  <Label>题型槽位</Label>
                  <SlotsEditor slots={manualSlots} onChange={setManualSlots} />
                </div>
              </div>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="compose-paper-name">试卷名称</Label>
              <Input
                id="compose-paper-name"
                value={paperName}
                onChange={(e) => {
                  setPaperName(e.target.value);
                  setPaperNameTouched(true);
                }}
                placeholder="默认按科目 + 日期生成"
              />
            </div>

            <Accordion type="single" collapsible>
              <AccordionItem value="advanced">
                <AccordionTrigger>高级选项</AccordionTrigger>
                <AccordionContent className="divide-y divide-border">
                  <OptionSwitch
                    label="人工审核"
                    description="组卷完成后先进入人工审核再保存试卷"
                    checked={requireHumanReview}
                    onChange={setRequireHumanReview}
                  />
                  <OptionSwitch
                    label="AI 补题"
                    description="题量不足时用 AI 生成题目补齐"
                    checked={autoAiBackfill}
                    onChange={setAutoAiBackfill}
                  />
                  <OptionSwitch
                    label="避开已用题目"
                    description="排除历史试卷中已使用过的题目"
                    checked={avoidUsed}
                    onChange={setAvoidUsed}
                  />
                  <OptionSwitch
                    label="按题干去重"
                    description="去除题干高度相似的重复题"
                    checked={dedupByStem}
                    onChange={setDedupByStem}
                  />
                  <OptionNumber
                    label="检索页数上限"
                    description="每个槽位最多抓取的搜索结果页数（1-8）"
                    value={maxPages}
                    min={1}
                    max={8}
                    onChange={setMaxPages}
                  />
                  <OptionNumber
                    label="最低质量分"
                    description="低于该分数的候选题将被过滤（0-100）"
                    value={minQualityScore}
                    min={0}
                    max={100}
                    onChange={setMinQualityScore}
                  />
                  <OptionNumber
                    label="AI 评审通过分"
                    description="自动评审的及格线（0-100）"
                    value={judgePassScore}
                    min={0}
                    max={100}
                    onChange={setJudgePassScore}
                  />
                </AccordionContent>
              </AccordionItem>
            </Accordion>

            <div className="flex items-center gap-2">
              <Button onClick={startCompose} disabled={running}>
                {running ? <Spinner className="text-primary-foreground" /> : <Layers />}
                开始组卷
              </Button>
              {running ? (
                <Button variant="outline" onClick={stopCompose}>
                  <Square /> 停止
                </Button>
              ) : null}
            </div>

            {composeTaskId && !task?.result ? <TaskProgressPanel taskId={composeTaskId} /> : null}
          </CardContent>
        </Card>

        {pendingReview && composeTaskId ? (
          <Alert variant="info">
            <ClipboardCheck />
            <AlertTitle>已进入人工审核</AlertTitle>
            <AlertDescription className="flex flex-wrap items-center gap-2">
              组卷草稿已生成，等待人工确认后保存试卷。
              <Button size="sm" variant="outline" onClick={() => onGotoReview(composeTaskId)}>
                前往人工审核
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        {task?.result ? <ComposeResultCard result={task.result} /> : null}
      </div>

      <Dialog open={createOpen} onOpenChange={setCreateOpen}>
        <DialogContent className="max-h-[85vh] max-w-xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新建蓝图</DialogTitle>
            <DialogDescription>定义题型配比，保存后可在组卷时一键复用</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="bp-name">蓝图名称</Label>
              <Input
                id="bp-name"
                value={bpForm.name}
                onChange={(e) => setBpForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="例如：高一数学期中标准卷"
              />
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>学科</Label>
                <SubjectSelect value={bpForm.subject} onValueChange={(v) => setBpForm((f) => ({ ...f, subject: v }))} />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="bp-topic">主题 / 知识点</Label>
                <Input
                  id="bp-topic"
                  value={bpForm.topic}
                  onChange={(e) => setBpForm((f) => ({ ...f, topic: e.target.value }))}
                  placeholder="可选"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label>题型槽位</Label>
              <SlotsEditor slots={bpForm.slots} onChange={(slots) => setBpForm((f) => ({ ...f, slots }))} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCreateOpen(false)}>
              取消
            </Button>
            <Button onClick={submitBlueprint} disabled={createMut.isPending}>
              {createMut.isPending ? <Spinner className="text-primary-foreground" /> : null}
              保存蓝图
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>删除蓝图</DialogTitle>
            <DialogDescription>确定删除蓝图「{deleting?.name}」吗？此操作不可撤销。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              disabled={removeMut.isPending}
              onClick={() => deleting && removeMut.mutate(deleting.id)}
            >
              {removeMut.isPending ? <Spinner className="text-primary-foreground" /> : <Trash2 />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

