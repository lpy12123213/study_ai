import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Brain, Sparkles, StopCircle } from "lucide-react";
import { generateLibraryQuestions, libraryApi } from "@/features/question-library/api";
import { DEFAULT_SUBJECT, DIFFICULTIES, QUESTION_TYPES } from "@/shared/api/types";
import type { LibraryPreview, TaskStep } from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { clamp } from "@/lib/format";
import { SubjectSelect } from "@/components/question/subject-select";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";
import { StepTimeline } from "@/components/task/step-timeline";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { GENERATION_STAGES } from "../model/shared";
import { apiErrorText } from "../model/shared";
import { parseKnowledgePoints } from "../model/shared";
import { useTaskStream } from "../model/use-task-stream";


// ---------------- AI 出题 ----------------

export function GeneratePanel({ onPreview }: { onPreview: (p: LibraryPreview) => void }) {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  const stream = useTaskStream("question_library_generate");
  const [form, setForm] = useState({
    subject: DEFAULT_SUBJECT as string,
    topic: "",
    difficulty: "all",
    questionType: "all",
    count: 5,
    mode: "standard" as "standard" | "infinite",
    knowledgePoints: "",
    useStudyArchive: true,
    useReferenceQuestions: true,
    referenceSource: "any" as "any" | "gaokao" | "mock" | "joint",
    referenceYearRange: "all" as "all" | "3" | "5",
    streamReasoning: false,
  });
  const [stageMap, setStageMap] = useState<Record<string, { label: string; order: number; summary: string }>>({});
  const [finished, setFinished] = useState(false);
  const [reasoning, setReasoning] = useState("");
  const [reasoningOpen, setReasoningOpen] = useState(true);

  const setField = <K extends keyof typeof form>(key: K, value: (typeof form)[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const currentOrder = useMemo(
    () => Math.max(0, ...Object.values(stageMap).map((s) => s.order)),
    [stageMap],
  );

  const steps: TaskStep[] = useMemo(
    () =>
      GENERATION_STAGES.map((s) => {
        const seen = stageMap[s.id];
        let status = "pending";
        if (finished) status = "completed";
        else if (seen) status = s.order < currentOrder ? "completed" : "running";
        return {
          id: s.id,
          title: seen?.summary ? `${s.label}（${seen.summary}）` : s.label,
          status,
        };
      }),
    [stageMap, finished, currentOrder],
  );

  const hasProgress = Object.keys(stageMap).length > 0 || stream.running || stream.taskId !== null;

  const submit = () => {
    const topic = form.topic.trim();
    if (!form.subject) {
      toast({ title: "请选择学科", variant: "warning" });
      return;
    }
    if (!topic) {
      toast({ title: "请填写主题", description: "例如：二次函数", variant: "warning" });
      return;
    }
    setStageMap({});
    setFinished(false);
    setReasoning("");
    stream.start(
      `${topic} 出题`,
      (handlers) =>
        generateLibraryQuestions(
          {
            subject: form.subject,
            topic,
            difficulty: form.difficulty === "all" ? "" : form.difficulty,
            question_type: form.questionType === "all" ? "" : form.questionType,
            count: clamp(Math.round(form.count) || 5, 1, 30),
            mode: form.mode,
            knowledge_points: parseKnowledgePoints(form.knowledgePoints),
            use_study_archive: form.useStudyArchive,
            use_reference_questions: form.useReferenceQuestions,
            reference_source: form.referenceSource,
            reference_year_range: form.referenceYearRange,
            stream_reasoning: form.streamReasoning,
          },
          handlers,
        ),
      {
        onEvent: (ev) => {
          if (ev.type === "progress") {
            const sid = String(ev.data?.stage_id || ev.data?.phase || "");
            if (sid) {
              setStageMap((m) => ({
                ...m,
                [sid]: {
                  label: String(ev.data?.stage_label || ev.data?.label || sid),
                  order: Number(ev.data?.stage_order) || 999,
                  summary: String(ev.data?.summary || ""),
                },
              }));
            }
          } else if (ev.type === "reasoning_delta") {
            const c = typeof ev.data?.content === "string" ? ev.data.content : "";
            if (c) setReasoning((t) => (t + c).slice(-60000));
          } else if (ev.type === "reasoning_status") {
            const msg = typeof ev.data?.message === "string" ? ev.data.message : "";
            if (msg) {
              const label = String(ev.data?.stage_label || "推理");
              setReasoning((t) => `${t}${t ? "\n" : ""}【${label}】${msg}`.slice(-60000));
            }
          }
        },
        onDoneEvent: (data) => {
          setFinished(true);
          queryClient.invalidateQueries({ queryKey: ["library-latest-pending-preview"] });
          const pid = String(data?.preview_id || data?.result?.preview_id || "");
          if (!pid) return;
          libraryApi
            .preview(pid)
            .then((pv) => {
              toast({
                title: "出题完成",
                description: `已生成 ${pv.draft_count ?? pv.draft_questions?.length ?? 0} 道草稿，请审核`,
                variant: "success",
              });
              onPreview(pv);
            })
            .catch((err) =>
              toast({ title: "加载预览失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" }),
            );
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Sparkles className="size-4 text-primary" />
            AI 出题
          </CardTitle>
          <CardDescription>基于学习资料与参考题生成新题，完成后进入预览审核再入库</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-1.5">
              <Label>学科（必填）</Label>
              <SubjectSelect value={form.subject} onValueChange={(v) => setField("subject", v)} />
            </div>
            <div className="space-y-1.5">
              <Label>主题（必填）</Label>
              <Input
                value={form.topic}
                onChange={(e) => setField("topic", e.target.value)}
                placeholder="例如：二次函数"
              />
            </div>
            <div className="space-y-1.5">
              <Label>难度</Label>
              <Select value={form.difficulty} onValueChange={(v) => setField("difficulty", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">不限</SelectItem>
                  {DIFFICULTIES.map((d) => (
                    <SelectItem key={d} value={d}>
                      {d}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>题型</Label>
              <Select value={form.questionType} onValueChange={(v) => setField("questionType", v)}>
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">不限</SelectItem>
                  {QUESTION_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>数量（1-30）</Label>
              <Input
                type="number"
                min={1}
                max={30}
                value={form.count}
                onChange={(e) => setField("count", Number(e.target.value))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>生成模式</Label>
              <RadioGroup
                value={form.mode}
                onValueChange={(v) => setField("mode", v as "standard" | "infinite")}
                className="flex h-9 items-center gap-4"
              >
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <RadioGroupItem value="standard" />
                  标准批次
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <RadioGroupItem value="infinite" />
                  持续生成
                </label>
              </RadioGroup>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label>知识点（逗号分隔，可空）</Label>
            <Input
              value={form.knowledgePoints}
              onChange={(e) => setField("knowledgePoints", e.target.value)}
              placeholder="例如：顶点式，判别式，韦达定理"
            />
          </div>

          <div className="grid gap-3 md:grid-cols-3">
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">使用学习资料</span>
              <Switch checked={form.useStudyArchive} onCheckedChange={(v) => setField("useStudyArchive", v)} />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">使用参考题</span>
              <Switch
                checked={form.useReferenceQuestions}
                onCheckedChange={(v) => setField("useReferenceQuestions", v)}
              />
            </label>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">透传生成推理</span>
              <Switch checked={form.streamReasoning} onCheckedChange={(v) => setField("streamReasoning", v)} />
            </label>
          </div>

          {form.useReferenceQuestions ? (
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label>参考题来源</Label>
                <Select
                  value={form.referenceSource}
                  onValueChange={(v) => setField("referenceSource", v as typeof form.referenceSource)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="any">不限来源</SelectItem>
                    <SelectItem value="gaokao">高考</SelectItem>
                    <SelectItem value="mock">模拟</SelectItem>
                    <SelectItem value="joint">联考</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>参考题年份范围</Label>
                <Select
                  value={form.referenceYearRange}
                  onValueChange={(v) => setField("referenceYearRange", v as typeof form.referenceYearRange)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">全部年份</SelectItem>
                    <SelectItem value="3">近 3 年</SelectItem>
                    <SelectItem value="5">近 5 年</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          ) : null}

          <div className="flex items-center gap-2">
            <Button onClick={submit} disabled={stream.running}>
              {stream.running ? <Spinner className="text-primary-foreground" /> : <Sparkles />}
              {stream.running ? "生成中…" : "开始出题"}
            </Button>
            {stream.running ? (
              <Button variant="outline" onClick={stream.stop}>
                <StopCircle />
                停止
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {hasProgress ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">生成进度</CardTitle>
            <CardDescription>出题流水线共 11 个阶段，完成后自动进入预览审核</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {stream.taskId ? <TaskProgressPanel taskId={stream.taskId} showSteps={false} /> : null}
            <StepTimeline steps={steps} />
          </CardContent>
        </Card>
      ) : null}

      {form.streamReasoning && (reasoning || stream.running) ? (
        <Card>
          <CardHeader className="pb-2">
            <button
              type="button"
              className="flex w-full cursor-pointer items-center justify-between text-left"
              onClick={() => setReasoningOpen((v) => !v)}
            >
              <CardTitle className="flex items-center gap-2 text-base">
                <Brain className="size-4 text-primary" />
                生成推理
              </CardTitle>
              <span className="text-xs text-muted-foreground">{reasoningOpen ? "收起" : "展开"}</span>
            </button>
          </CardHeader>
          {reasoningOpen ? (
            <CardContent>
              {reasoning ? (
                <pre className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-muted/60 p-3 font-mono text-xs leading-relaxed text-muted-foreground">
                  {reasoning}
                </pre>
              ) : (
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <Spinner />
                  等待模型推理输出…
                </div>
              )}
            </CardContent>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}

