import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router";
import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, ListChecks, Search, Sparkles } from "lucide-react";
import { ApiError } from "@/shared/api/http-client";
import { evaluateApi } from "@/features/paper-compose/api";
import { papersApi } from "@/features/paper-library/api";
import type { QuestionEvaluateResult, SearchQuestion } from "@/shared/api/types";
import { DEFAULT_SUBJECT, DIFFICULTIES, EDU_LEVELS, QUESTION_TYPES } from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { clamp, formatDate } from "@/lib/format";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Spinner } from "@/components/ui/spinner";
import { QuestionCard } from "@/components/question/question-card";
import { SubjectSelect } from "@/components/question/subject-select";
import { ANY_VALUE } from "../model/utils";
import { errMsg } from "../model/utils";
import { isZujuanLoginError } from "../model/utils";
import { toInt } from "../model/utils";
import { knowledgePointsText } from "../model/utils";
import { EvalResultPanel } from "./eval-result-panel";


// ---------------- 页签 1：搜题 ----------------

export function SearchTab({ initialKeyword = "" }: { initialKeyword?: string }) {
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

