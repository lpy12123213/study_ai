import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  Layers,
  ListChecks,
  Plus,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Trash2,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { blueprintsApi, composePaper, evaluateApi } from "@/features/paper-compose/api";
import { papersApi } from "@/features/paper-library/api";
import { tasksApi } from "@/features/task-center/api";
import type {
  Blueprint,
  BlueprintSlot,
  ComposeDraft,
  ComposeDraftQuestion,
  QuestionEvaluateResult,
  SearchQuestion,
} from "@/shared/api/types";
import { DEFAULT_SUBJECT, DIFFICULTIES, EDU_LEVELS, QUESTION_TYPES, TASK_STATUS_LABELS } from "@/shared/api/types";
import type { ActiveTask } from "@/stores/tasks";
import { useTasksStore } from "@/stores/tasks";
import { useUiStore } from "@/stores/ui";
import { clamp, formatDate } from "@/lib/format";
import { parseEnumParam, parseStringParam, updateSearchParams } from "@/shared/lib/search-params";
import { cn } from "@/lib/utils";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { QuestionCard } from "@/components/question/question-card";
import { SubjectSelect } from "@/components/question/subject-select";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";

/** Radix Select 不允许空字符串 value，用哨兵值表示“不限”。 */
const ANY_VALUE = "__any__";

function errMsg(err: unknown): string {
  return err instanceof ApiError ? err.message : "网络异常，请稍后重试";
}

/** 组卷网登录态失效的错误码特征（crawler client 经 error 字段透出）。 */
function isZujuanLoginError(error?: string): boolean {
  const e = String(error ?? "");
  return e.includes("zujuan_cookie") || e.includes("login_required") || e.includes("cookie_expired");
}

function toInt(v: string, fallback: number): number {
  const n = Number.parseInt(v, 10);
  return Number.isNaN(n) ? fallback : n;
}

/** SearchQuestion.knowledge_points 可能是数组或字符串，统一成字符串。 */
function knowledgePointsText(q: SearchQuestion): string {
  const kp = q.knowledge_points;
  if (Array.isArray(kp)) return kp.filter(Boolean).join("、");
  return String(kp ?? "");
}

/** 组卷草稿题目 id（camelCase / snake_case 兼容）。 */
function draftQuestionId(q: ComposeDraftQuestion): string {
  return String(q.questionId ?? q.question_id ?? "").trim();
}

function verdictVariant(v?: string): "success" | "warning" | "destructive" | "muted" {
  if (v === "好题") return "success";
  if (v === "普通题") return "warning";
  if (v === "差题") return "destructive";
  return "muted";
}

/** 从任务详情（DB 版 / 内存兜底版）中提取组卷草稿。 */
function extractComposeDraft(detail: unknown): ComposeDraft | null {
  if (!detail || typeof detail !== "object") return null;
  const d = detail as Record<string, any>;
  const fromResult = d.result?.composeDraft;
  if (fromResult && typeof fromResult === "object") return fromResult as ComposeDraft;
  if (d.composeDraft && typeof d.composeDraft === "object") return d.composeDraft as ComposeDraft;
  const events = Array.isArray(d.events) ? (d.events as any[]) : [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const data = events[i]?.data;
    const draft = data?.composeDraft ?? data?.compose_draft;
    if (draft && typeof draft === "object") return draft as ComposeDraft;
  }
  return null;
}

/** 生成试卷 / 组卷结果的统一结果卡。 */
function ComposeResultCard({ result }: { result: any }) {
  const navigate = useNavigate();
  const pid = result?.paperId ?? result?.id;
  const name = String(result?.paperName ?? result?.name ?? "未命名试卷");
  const count =
    result?.questionCount ?? (Array.isArray(result?.questions) ? (result.questions as unknown[]).length : undefined);
  return (
    <Card className="border-success/40 bg-success/5">
      <CardContent className="flex items-center gap-3 p-4">
        <CheckCircle2 className="size-5 shrink-0 text-success" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{name}</div>
          <div className="text-xs text-muted-foreground">
            试卷已生成{typeof count === "number" ? `，共 ${count} 题` : ""}
          </div>
        </div>
        {pid != null ? (
          <Button size="sm" onClick={() => navigate(`/papers/${pid}`)}>
            查看试卷
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

/** AI 鉴别结果展开区：verdict + 总分 + 维度条形 + 亮点/问题。 */
function EvalResultPanel({ result }: { result: QuestionEvaluateResult }) {
  return (
    <div className="mt-2 space-y-3 rounded-lg border border-border bg-muted/40 p-3 animate-fade-in">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={verdictVariant(result.verdict)}>{result.verdict || "未评级"}</Badge>
        <span className="text-sm font-medium tabular-nums">{result.overall_score} 分</span>
        {result.summary ? <span className="text-xs text-muted-foreground">{result.summary}</span> : null}
      </div>
      {result.dimensions.length > 0 ? (
        <div className="space-y-1.5">
          {result.dimensions.map((d, i) => (
            <div key={`${d.name}-${i}`} className="flex items-center gap-2 text-xs" title={d.comment || undefined}>
              <span className="w-16 shrink-0 text-muted-foreground">{d.name}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary"
                  style={{ width: `${clamp(d.score, 0, 10) * 10}%` }}
                />
              </div>
              <span className="w-9 shrink-0 text-right tabular-nums text-muted-foreground">{d.score}/10</span>
            </div>
          ))}
        </div>
      ) : null}
      {result.highlights && result.highlights.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-success">亮点</div>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
            {result.highlights.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {result.issues && result.issues.length > 0 ? (
        <div>
          <div className="mb-1 text-xs font-medium text-destructive">问题</div>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
            {result.issues.map((it, i) => (
              <li key={i}>{it}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

/** 题型槽位行编辑器（蓝图表单 / 手工配置共用）。 */
function SlotsEditor({ slots, onChange }: { slots: BlueprintSlot[]; onChange: (slots: BlueprintSlot[]) => void }) {
  const update = (i: number, patch: Partial<BlueprintSlot>) =>
    onChange(slots.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  const remove = (i: number) => onChange(slots.filter((_, idx) => idx !== i));
  const add = () => onChange([...slots, { questionType: "单选题", count: 5, difficulty: "中等" }]);
  return (
    <div className="space-y-2">
      {slots.map((slot, i) => (
        <div key={i} className="flex items-center gap-2">
          <Select value={slot.questionType} onValueChange={(v) => update(i, { questionType: v })}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="题型" />
            </SelectTrigger>
            <SelectContent>
              {QUESTION_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="number"
            min={1}
            max={50}
            className="w-20"
            value={slot.count}
            onChange={(e) => update(i, { count: clamp(toInt(e.target.value, 1), 1, 50) })}
            aria-label="数量"
          />
          <Select
            value={slot.difficulty || "中等"}
            onValueChange={(v) => update(i, { difficulty: v })}
          >
            <SelectTrigger className="w-24">
              <SelectValue placeholder="难度" />
            </SelectTrigger>
            <SelectContent>
              {DIFFICULTIES.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-destructive"
            onClick={() => remove(i)}
            aria-label="删除此行"
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus /> 添加一行
      </Button>
    </div>
  );
}

function validSlots(slots: BlueprintSlot[]): BlueprintSlot[] {
  // 后端把空难度归为「中等」并作为检索过滤条件（_difficulty_from_slot），这里始终显式带上难度
  return slots
    .filter((s) => s.questionType && s.count > 0)
    .map((s) => ({ questionType: s.questionType, count: s.count, difficulty: s.difficulty || "中等" }));
}

/** 高级选项里的开关行。 */
function OptionSwitch({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <div className="text-sm">{label}</div>
        {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
      </div>
      <Switch checked={checked} onCheckedChange={onChange} />
    </div>
  );
}

/** 高级选项里的数字行。 */
function OptionNumber({
  label,
  description,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  description?: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="min-w-0">
        <div className="text-sm">{label}</div>
        {description ? <div className="text-xs text-muted-foreground">{description}</div> : null}
      </div>
      <Input
        type="number"
        min={min}
        max={max}
        className="w-24"
        value={value}
        onChange={(e) => onChange(clamp(toInt(e.target.value, value), min, max))}
      />
    </div>
  );
}

// ---------------- 页签 1：搜题 ----------------

function SearchTab({ initialKeyword = "" }: { initialKeyword?: string }) {
  const navigate = useNavigate();
  const toast = useUiStore((s) => s.toast);

  const [keyword, setKeyword] = useState(initialKeyword);
  const [subject, setSubject] = useState<string>(DEFAULT_SUBJECT);
  const [eduLevel, setEduLevel] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [questionType, setQuestionType] = useState("");
  const [limit, setLimit] = useState(20);
  const [minQuality, setMinQuality] = useState(0);

  const [checked, setChecked] = useState<ReadonlySet<string>>(new Set());
  const [basket, setBasket] = useState<SearchQuestion[]>([]);
  const [evalResults, setEvalResults] = useState<Record<string, QuestionEvaluateResult>>({});

  const [paperDialogOpen, setPaperDialogOpen] = useState(false);
  const [paperName, setPaperName] = useState("");

  const searchMut = useMutation({
    mutationFn: () =>
      evaluateApi.search({
        query: keyword.trim(),
        subject,
        edu_level: eduLevel || undefined,
        difficulty: difficulty || undefined,
        question_type: questionType || undefined,
        limit,
        min_quality_score: minQuality,
      }),
    onSuccess: (data) => {
      // 组卷网登录失效经 error 字段的 zujuan_cookie_* 错误码透出（响应模型无 login_required 字段）
      if (!data.success && isZujuanLoginError(data.error)) {
        useUiStore.getState().setZujuanLoginRequired(true);
      }
    },
    onError: (err) =>
      toast({
        title: "搜题失败",
        description:
          err instanceof ApiError && err.code === "subject_edu_mismatch"
            ? "学科与学段不匹配，请调整后重试"
            : errMsg(err),
        variant: "destructive",
      }),
  });

  const evalMut = useMutation({
    mutationFn: (qs: SearchQuestion[]) =>
      evaluateApi.evaluate({
        subject,
        questions: qs.map((q) => ({
          question_id: q.question_id,
          stem: q.stem ?? "",
          type: q.type ?? "",
          difficulty: q.difficulty ?? "",
          knowledge_points: knowledgePointsText(q),
          source: q.source ?? "",
          source_url: q.source_url ?? "",
          date: q.date ?? "",
          quality_score: q.quality_score ?? null,
          quality_flags: q.quality_flags ?? [],
          difficulty_value: q.difficulty_value ?? null,
        })),
      }),
    onSuccess: (data, qs) => {
      setEvalResults((prev) => {
        const next = { ...prev };
        data.results.forEach((r, i) => {
          const qid = r.question_id || qs[i]?.question_id || "";
          if (qid) next[qid] = r;
        });
        return next;
      });
      toast({ title: "AI 鉴别完成", description: `共鉴别 ${data.results.length} 题`, variant: "success" });
    },
    onError: (err) => toast({ title: "AI 鉴别失败", description: errMsg(err), variant: "destructive" }),
  });

  const createMut = useMutation({
    mutationFn: (name: string) =>
      papersApi.create({
        paper_name: name,
        questions: basket.map((q) => ({
          question_id: q.question_id,
          type: q.type,
          difficulty: q.difficulty,
          knowledge_point: knowledgePointsText(q) || undefined,
          source_url: q.source_url,
        })),
      }),
    onSuccess: (data, name) => {
      toast({ title: "试卷创建成功", description: `「${name}」共 ${basket.length} 题`, variant: "success" });
      setPaperDialogOpen(false);
      setBasket([]);
      navigate(`/papers/${data.paper_id}`);
    },
    onError: (err) => toast({ title: "生成试卷失败", description: errMsg(err), variant: "destructive" }),
  });

  const result = searchMut.data;
  const questions = result?.questions ?? [];

  // 学科自带学段（初中*/高中*），后端 resolve_subject 严格校验 subject_edu_mismatch——前端先约束可选项
  const subjectLevel = subject.startsWith("初中") ? "初中" : subject.startsWith("高中") ? "高中" : "";
  const eduOptions = EDU_LEVELS.filter((lv) => !subjectLevel || lv === subjectLevel);

  const changeSubject = (v: string) => {
    setSubject(v);
    const lv = v.startsWith("初中") ? "初中" : v.startsWith("高中") ? "高中" : "";
    if (lv && eduLevel && eduLevel !== lv) setEduLevel("");
  };

  const submitSearch = (e: FormEvent) => {
    e.preventDefault();
    if (!keyword.trim()) {
      toast({ title: "请输入关键词", variant: "warning" });
      return;
    }
    setChecked(new Set());
    searchMut.mutate();
  };

  const toggleChecked = (qid: string, v: boolean) =>
    setChecked((prev) => {
      const next = new Set(prev);
      if (v) next.add(qid);
      else next.delete(qid);
      return next;
    });

  const toggleBasket = (q: SearchQuestion) =>
    setBasket((prev) =>
      prev.some((x) => x.question_id === q.question_id)
        ? prev.filter((x) => x.question_id !== q.question_id)
        : [...prev, q],
    );

  const runEvaluate = () => {
    const qs = questions.filter((q) => checked.has(q.question_id));
    if (qs.length === 0) {
      toast({ title: "请先勾选要鉴别的题目", variant: "warning" });
      return;
    }
    evalMut.mutate(qs);
  };

  const openPaperDialog = () => {
    setPaperName(`${subject}精选试题 ${formatDate(new Date().toISOString())}`);
    setPaperDialogOpen(true);
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle>搜题</CardTitle>
          <CardDescription>按关键词检索组卷网题库，可叠加学段、难度、题型与质量分过滤</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submitSearch} className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <div className="space-y-1.5 sm:col-span-2 lg:col-span-3">
              <Label htmlFor="compose-keyword">关键词</Label>
              <Input
                id="compose-keyword"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="例如：二次函数 顶点式"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label>学科</Label>
              <SubjectSelect value={subject} onValueChange={changeSubject} />
            </div>
            <div className="space-y-1.5">
              <Label>学段</Label>
              <Select value={eduLevel || ANY_VALUE} onValueChange={(v) => setEduLevel(v === ANY_VALUE ? "" : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY_VALUE}>不限</SelectItem>
                  {eduOptions.map((lv) => (
                    <SelectItem key={lv} value={lv}>
                      {lv}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label>难度</Label>
              <Select value={difficulty || ANY_VALUE} onValueChange={(v) => setDifficulty(v === ANY_VALUE ? "" : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY_VALUE}>不限</SelectItem>
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
              <Select
                value={questionType || ANY_VALUE}
                onValueChange={(v) => setQuestionType(v === ANY_VALUE ? "" : v)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="不限" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ANY_VALUE}>不限</SelectItem>
                  {QUESTION_TYPES.map((t) => (
                    <SelectItem key={t} value={t}>
                      {t}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="compose-limit">数量</Label>
              <Input
                id="compose-limit"
                type="number"
                min={1}
                max={50}
                value={limit}
                onChange={(e) => setLimit(clamp(toInt(e.target.value, 20), 1, 50))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>最低质量分：{minQuality}</Label>
              <div className="flex h-9 items-center">
                <Slider
                  value={[minQuality]}
                  min={0}
                  max={100}
                  step={5}
                  onValueChange={(v) => setMinQuality(v[0] ?? 0)}
                />
              </div>
            </div>
            <div className="flex items-end sm:col-span-2 lg:col-span-3">
              <Button type="submit" disabled={searchMut.isPending}>
                {searchMut.isPending ? <Spinner className="text-primary-foreground" /> : <Search />}
                搜索题目
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {result && !result.success && isZujuanLoginError(result.error) ? (
        <Alert variant="warning">
          <AlertTriangle />
          <AlertTitle>组卷网登录已失效</AlertTitle>
          <AlertDescription>请运行 scripts/登录组卷网.bat 重新登录后再试。</AlertDescription>
        </Alert>
      ) : null}

      {result && !result.success && !isZujuanLoginError(result.error) ? (
        <Alert variant="destructive">
          <AlertTriangle />
          <AlertTitle>搜索失败</AlertTitle>
          <AlertDescription>{result.error || "未知错误"}</AlertDescription>
        </Alert>
      ) : null}

      {searchMut.isPending ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-28 w-full rounded-xl" />
          ))}
        </div>
      ) : null}

      {result?.success && questions.length === 0 ? (
        <EmptyState icon={Search} title="未找到匹配题目" description="换个关键词或放宽筛选条件再试" />
      ) : null}

      {questions.length > 0 ? (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-muted-foreground">
              命中 {result?.count ?? questions.length} 题{checked.size > 0 ? `，已勾选 ${checked.size} 题` : ""}
            </span>
            <Button size="sm" variant="outline" onClick={runEvaluate} disabled={checked.size === 0 || evalMut.isPending}>
              {evalMut.isPending ? <Spinner /> : <Sparkles />}
              AI 鉴别
            </Button>
          </div>
          {questions.map((q, idx) => {
            const qid = q.question_id || `idx-${idx}`;
            const inBasket = basket.some((x) => x.question_id === q.question_id);
            return (
              <div key={qid}>
                <QuestionCard
                  question={q}
                  selected={checked.has(qid)}
                  onSelect={(v) => toggleChecked(qid, v)}
                  actions={
                    <Button size="sm" variant={inBasket ? "secondary" : "outline"} onClick={() => toggleBasket(q)}>
                      {inBasket ? "移出" : "加入试题篮"}
                    </Button>
                  }
                />
                {evalResults[qid] ? <EvalResultPanel result={evalResults[qid]} /> : null}
              </div>
            );
          })}
        </div>
      ) : null}

      {basket.length > 0 ? (
        <div className="sticky bottom-4 z-10 flex items-center gap-3 rounded-xl border border-border bg-card/95 px-4 py-3 shadow-lift backdrop-blur animate-slide-up">
          <ListChecks className="size-4 shrink-0 text-primary" />
          <span className="text-sm">
            试题篮已选 <span className="font-semibold tabular-nums">{basket.length}</span> 题
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setBasket([])}>
              清空
            </Button>
            <Button size="sm" onClick={openPaperDialog}>
              生成试卷
            </Button>
          </div>
        </div>
      ) : null}

      <Dialog open={paperDialogOpen} onOpenChange={setPaperDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>生成试卷</DialogTitle>
            <DialogDescription>将试题篮中的 {basket.length} 道题保存为新试卷</DialogDescription>
          </DialogHeader>
          <div className="space-y-1.5">
            <Label htmlFor="basket-paper-name">试卷名称</Label>
            <Input
              id="basket-paper-name"
              value={paperName}
              onChange={(e) => setPaperName(e.target.value)}
              placeholder="请输入试卷名称"
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPaperDialogOpen(false)}>
              取消
            </Button>
            <Button
              onClick={() => {
                const name = paperName.trim();
                if (!name) {
                  toast({ title: "请输入试卷名称", variant: "warning" });
                  return;
                }
                createMut.mutate(name);
              }}
              disabled={createMut.isPending}
            >
              {createMut.isPending ? <Spinner className="text-primary-foreground" /> : null}
              创建试卷
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---------------- 页签 2：蓝图组卷 ----------------

interface BlueprintFormState {
  name: string;
  subject: string;
  topic: string;
  slots: BlueprintSlot[];
}

function BlueprintTab({ onGotoReview }: { onGotoReview: (taskId: string) => void }) {
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

// ---------------- 页签 3：人工审核 ----------------

function DraftReview({ task }: { task: ActiveTask }) {
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

function ReviewTab({ focusTaskId }: { focusTaskId: string | null }) {
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

// ---------------- 页面 ----------------

export function ComposePage() {
  // tab 与审核任务 ID 入 URL（架构 §8.4）：/compose?tab=review&review=<taskId> 可直达
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseEnumParam(searchParams, "tab", ["search", "blueprint", "review"] as const) ?? "search";
  const reviewFocus = parseStringParam(searchParams, "review") ?? null;
  const setTab = (v: string) =>
    setSearchParams((prev) => updateSearchParams(prev, { tab: v === "search" ? null : v }), { replace: true });
  const gotoReview = (taskId: string) =>
    setSearchParams((prev) => updateSearchParams(prev, { tab: "review", review: taskId }));
  // 首页 Intent Workspace 带入的关键词预填（useState 初始化即消费，无需 effect）
  const location = useLocation();
  const [prefillKeyword] = useState(
    () => (location.state as { prefillKeyword?: string } | null)?.prefillKeyword ?? "",
  );

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 animate-fade-in">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">组卷工作室</h1>
        <p className="mt-1 text-sm text-muted-foreground">搜题鉴别、蓝图组卷与人工审核的一体化工作台</p>
      </header>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="search">
            <Search /> 搜题
          </TabsTrigger>
          <TabsTrigger value="blueprint">
            <Layers /> 蓝图组卷
          </TabsTrigger>
          <TabsTrigger value="review">
            <ClipboardCheck /> 人工审核
          </TabsTrigger>
        </TabsList>

        <TabsContent value="search" forceMount>
          <SearchTab initialKeyword={prefillKeyword} />
        </TabsContent>
        <TabsContent value="blueprint" forceMount>
          <BlueprintTab onGotoReview={gotoReview} />
        </TabsContent>
        <TabsContent value="review" forceMount>
          <ReviewTab focusTaskId={reviewFocus} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
