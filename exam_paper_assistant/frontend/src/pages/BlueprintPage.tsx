import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { motion, type Variants } from "framer-motion";
import { ChevronLeft, ChevronRight, Clipboard, FilePlus2, Filter, Layers, RefreshCcw, Sparkles } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Textarea } from "@/components/ui/textarea";
import { useAvailableFilters, useComposeBlueprint } from "@/hooks/useCrawlerTools";
import { useCreatePaper } from "@/hooks/usePapers";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useSubjects } from "@/hooks/useSubjects";
import { cn } from "@/lib/utils";
import type {
  BlueprintQuestionPreview,
  BlueprintSectionResult,
  BlueprintSlot,
  ComposeBlueprintResponse,
  Subject,
} from "@/types";

const EDU_LEVEL_NAME_BY_ID: Record<number, string> = {
  1: "小学",
  2: "初中",
  3: "高中",
  4: "中职",
};

function eduLevelFromSubject(subject: Subject | null): string {
  if (!subject) return "";
  return EDU_LEVEL_NAME_BY_ID[subject.edu_id] ?? "";
}

function normalizeInt(value: unknown, fallback: number): number {
  const n = typeof value === "number" ? value : Number(String(value ?? ""));
  if (!Number.isFinite(n)) return fallback;
  return Math.trunc(n);
}

function electiveModeLabel(mode: string): string {
  if (mode === "exclude") return "排除选修/选必";
  if (mode === "only") return "仅选修/选必";
  return "不过滤";
}

function slotTitle(slot: BlueprintSlot): string {
  const a = (slot.keyword || "").trim();
  const b = (slot.knowledge_point || "").trim();
  return a || b || "未命名槽位";
}

function toMultilineQuestionIds(questionIds: string[]): string {
  return (questionIds || []).filter(Boolean).join("\n");
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.06,
    },
  },
};

const itemVariants: Variants = {
  hidden: { y: 14, opacity: 0 },
  visible: {
    y: 0,
    opacity: 1,
    transition: {
      type: "spring",
      stiffness: 120,
    },
  },
};

const defaultSlots: BlueprintSlot[] = [
  { keyword: "", count: 4, difficulty: "中等" },
  { keyword: "", count: 4, difficulty: "中等" },
  { keyword: "", count: 2, difficulty: "中等" },
];

export default function BlueprintPage() {
  const navigate = useNavigate();
  const subjectsQuery = useSubjects();
  const createPaper = useCreatePaper();
  const composeBlueprint = useComposeBlueprint();

  const subjects = useMemo(() => subjectsQuery.data ?? [], [subjectsQuery.data]);

  const [subjectName, setSubjectName] = useLocalStorageState<string>(
    "epa_subject_name",
    "高中数学",
  );

  const [leftPanelCollapsed, setLeftPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_blueprint_left_panel_collapsed",
    false,
  );
  const [rightPanelCollapsed, setRightPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_blueprint_right_panel_collapsed",
    false,
  );

  const selectedSubject = useMemo(
    () => subjects.find((s) => s.name === subjectName) ?? null,
    [subjects, subjectName],
  );

  const eduLevel = useMemo(() => eduLevelFromSubject(selectedSubject), [selectedSubject]);

  const filtersQuery = useAvailableFilters(
    { subject: subjectName, edu_level: eduLevel },
    true,
  );

  const grades = filtersQuery.data?.grades ?? [];
  const questionTypes = filtersQuery.data?.question_types ?? [];
  const textbookVersions = filtersQuery.data?.textbook_versions ?? [];
  const provinces = filtersQuery.data?.provinces ?? [];
  const electiveModes = filtersQuery.data?.elective_modes ?? ["include", "exclude", "only"];
  const paperTypesByGrade = filtersQuery.data?.paper_types_by_grade ?? {};

  const [learnGradeId, setLearnGradeId] = useState<number>(0);
  const [textbookVersion, setTextbookVersion] = useState<string>("");
  const [provinceId, setProvinceId] = useState<number>(-1);
  const [paperTypeId, setPaperTypeId] = useState<number>(0);
  const [electiveMode, setElectiveMode] = useState<string>("include");

  const [strictSubject, setStrictSubject] = useState<boolean>(true);
  const [dedupByStem, setDedupByStem] = useState<boolean>(true);
  const [minQualityScore, setMinQualityScore] = useState<number>(60);
  const [maxPages, setMaxPages] = useState<number>(2);
  const [perSlotExpand, setPerSlotExpand] = useState<number>(3);

  const [slots, setSlots] = useState<BlueprintSlot[]>(defaultSlots);
  const [composeResult, setComposeResult] = useState<ComposeBlueprintResponse | null>(null);
  const [paperName, setPaperName] = useState<string>(() => {
    const stamp = format(new Date(), "yyyyMMdd");
    return `蓝图组卷-${stamp}`;
  });
  const [uiMessage, setUiMessage] = useState<string | null>(null);

  useEffect(() => {
    setUiMessage(null);
    setComposeResult(null);
    setLearnGradeId(0);
    setTextbookVersion("");
    setProvinceId(-1);
    setPaperTypeId(0);
    setElectiveMode("include");
  }, [subjectName]);

  const paperTypeOptions = useMemo(() => {
    const key = learnGradeId ? String(learnGradeId) : "";
    const list = key ? paperTypesByGrade[key] : null;
    return Array.isArray(list) ? list : [];
  }, [paperTypesByGrade, learnGradeId]);

  const normalizedSlots = useMemo(() => {
    return (slots || [])
      .map((s) => ({
        keyword: (s.keyword || "").trim(),
        knowledge_point: (s.knowledge_point || "").trim(),
        count: normalizeInt(s.count, 0),
        difficulty: (s.difficulty || "").trim(),
        question_type: (s.question_type || "").trim(),
        max_pages: s.max_pages ? normalizeInt(s.max_pages, 0) : undefined,
      }))
      .filter((s) => s.count > 0 && (!!s.keyword || !!s.knowledge_point));
  }, [slots]);

  const questionIds = useMemo(
    () => composeResult?.question_ids ?? [],
    [composeResult?.question_ids],
  );

  const sections = useMemo<BlueprintSectionResult[]>(
    () => composeResult?.sections ?? [],
    [composeResult?.sections],
  );

  const preview = useMemo<BlueprintQuestionPreview[]>(
    () => composeResult?.questions_preview ?? [],
    [composeResult?.questions_preview],
  );

  const handleSlotPatch = (idx: number, patch: Partial<BlueprintSlot>) => {
    setSlots((prev) => prev.map((s, i) => (i === idx ? { ...s, ...patch } : s)));
  };

  const handleAddSlot = () => {
    setSlots((prev) => [...prev, { keyword: "", count: 4, difficulty: "中等" }]);
  };

  const handleRemoveSlot = (idx: number) => {
    setSlots((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleResetSlots = () => {
    setSlots(defaultSlots);
    setComposeResult(null);
    setUiMessage(null);
  };

  const handleCompose = async () => {
    setUiMessage(null);
    if (!subjectName.trim()) {
      setUiMessage("请选择学科。");
      return;
    }
    if (normalizedSlots.length === 0) {
      setUiMessage("请至少填写一个槽位：关键词/知识点 + 数量。");
      return;
    }

    try {
      const res = await composeBlueprint.mutateAsync({
        blueprint: normalizedSlots,
        subject: subjectName,
        edu_level: eduLevel,
        learn_grade_id: learnGradeId || 0,
        textbook_version: textbookVersion || "",
        province_id: provinceId,
        paper_type_id: paperTypeId || 0,
        elective_mode: electiveMode || "",
        max_pages: normalizeInt(maxPages, 2),
        per_slot_expand: normalizeInt(perSlotExpand, 3),
        min_quality_score: normalizeInt(minQualityScore, 0),
        dedup_by_stem: !!dedupByStem,
        strict_subject: !!strictSubject,
      });

      setComposeResult(res);
      if (!res.success) {
        setUiMessage(res.error || "蓝图组卷失败，请检查筛选项与网络连接。");
      }
    } catch (error) {
      setComposeResult(null);
      setUiMessage(`请求失败：${formatUnknownError(error)}`);
    }
  };

  const handleCopyIds = async () => {
    setUiMessage(null);
    if (!questionIds.length) {
      setUiMessage("暂无题目 ID 可复制。");
      return;
    }
    const ok = await copyToClipboard(toMultilineQuestionIds(questionIds));
    setUiMessage(ok ? "已复制题目 ID 到剪贴板。" : "复制失败：浏览器不允许访问剪贴板。");
  };

  const handleCreatePaper = async () => {
    setUiMessage(null);
    const name = paperName.trim();
    if (!name) {
      setUiMessage("请填写试卷名称。");
      return;
    }
    if (!questionIds.length) {
      setUiMessage("请先生成题目 ID。");
      return;
    }

    try {
      const created = await createPaper.mutateAsync({
        paperName: name,
        questionIds,
      });
      navigate(`/papers/${created.paper_id}`);
    } catch (error) {
      setUiMessage(`创建试卷失败：${formatUnknownError(error)}`);
    }
  };

  return (
    <motion.div
      className="h-full overflow-y-auto bg-muted/30 p-6 md:p-8"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div variants={itemVariants} className="mb-8 flex flex-col gap-3">
        <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">蓝图组卷</h1>
            <p className="text-muted-foreground mt-2">
              按多个槽位一次性检索并拼装题目 ID 列表（只保存题号，合规下载）。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="secondary" className="bg-background/50 backdrop-blur border">
              学科：{subjectName || "-"}
            </Badge>
            <Badge variant="outline" className="bg-background/50 backdrop-blur">
              学段：{eduLevel || "自动"}
            </Badge>
          </div>
        </div>

        {uiMessage && (
          <div className="rounded-lg border bg-background/60 px-4 py-3 text-sm">
            {uiMessage}
          </div>
        )}
      </motion.div>

      <div
        className={cn(
          "grid gap-6",
          leftPanelCollapsed && rightPanelCollapsed
            ? "lg:grid-cols-[56px_56px]"
            : leftPanelCollapsed
              ? "lg:grid-cols-[56px_1fr]"
              : rightPanelCollapsed
                ? "lg:grid-cols-[1fr_56px]"
                : "lg:grid-cols-[5fr_7fr] xl:grid-cols-[4fr_8fr]",
        )}
      >
        <motion.section
          variants={itemVariants}
          className={cn("min-w-0", leftPanelCollapsed ? "space-y-0" : "space-y-6")}
        >
          {leftPanelCollapsed ? (
            <div className="h-full rounded-lg border bg-background/60 backdrop-blur-sm p-2 flex flex-col items-center gap-2">
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
              <Filter className="h-4 w-4 text-muted-foreground" />
            </div>
          ) : (
            <>
          <Card className="shadow-sm">
            <CardHeader className="space-y-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Filter className="h-4 w-4 text-primary" />
                    筛选项
                  </CardTitle>
                  <CardDescription>先选择学科，再加载可用筛选项。</CardDescription>
                </div>
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
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">学科</div>
                <select
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                  value={subjectName}
                  onChange={(e) => setSubjectName(e.target.value)}
                  disabled={subjectsQuery.isLoading}
                >
                  {subjects.map((s) => (
                    <option key={s.name} value={s.name}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-xs text-muted-foreground">
                  {filtersQuery.isLoading
                    ? "正在加载可用筛选项..."
                    : filtersQuery.isError
                      ? "加载失败：请检查后端服务"
                      : filtersQuery.data?.success === false
                        ? `加载失败：${filtersQuery.data?.error || "unknown"}`
                        : filtersQuery.data?.success
                          ? "已加载筛选项"
                          : "等待加载"}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => void filtersQuery.refetch()}
                  disabled={filtersQuery.isFetching}
                >
                  <RefreshCcw
                    className={cn("h-3.5 w-3.5", filtersQuery.isFetching && "animate-spin")}
                  />
                  刷新
                </Button>
              </div>

              <Separator />

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">年级</div>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                    value={String(learnGradeId)}
                    onChange={(e) => setLearnGradeId(normalizeInt(e.target.value, 0))}
                    disabled={!grades.length}
                  >
                    <option value="0">不限</option>
                    {grades.map((g) => (
                      <option key={g.id} value={String(g.id)}>
                        {g.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">试卷类型</div>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                    value={String(paperTypeId)}
                    onChange={(e) => setPaperTypeId(normalizeInt(e.target.value, 0))}
                    disabled={!paperTypeOptions.length}
                  >
                    <option value="0">不限</option>
                    {paperTypeOptions.map((p) => (
                      <option key={p.id} value={String(p.id)}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted-foreground">教材版本</div>
                <select
                  className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                  value={textbookVersion}
                  onChange={(e) => setTextbookVersion(e.target.value)}
                  disabled={!textbookVersions.length}
                >
                  <option value="">不限</option>
                  {textbookVersions.map((v) => (
                    <option key={v.id} value={v.name}>
                      {v.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">省份</div>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                    value={String(provinceId)}
                    onChange={(e) => setProvinceId(normalizeInt(e.target.value, -1))}
                    disabled={!provinces.length}
                  >
                    <option value="-1">不限</option>
                    {provinces.map((p) => (
                      <option key={p.id} value={String(p.id)}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">选修过滤</div>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                    value={electiveMode}
                    onChange={(e) => setElectiveMode(e.target.value)}
                  >
                    {electiveModes.map((m) => (
                      <option key={m} value={m}>
                        {electiveModeLabel(m)}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <Separator />

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">候选扩展倍数</div>
                  <Input
                    type="number"
                    value={perSlotExpand}
                    onChange={(e) => setPerSlotExpand(normalizeInt(e.target.value, 3))}
                    min={1}
                    max={6}
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">最大翻页数</div>
                  <Input
                    type="number"
                    value={maxPages}
                    onChange={(e) => setMaxPages(normalizeInt(e.target.value, 2))}
                    min={1}
                    max={8}
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">质量阈值</div>
                  <Input
                    type="number"
                    value={minQualityScore}
                    onChange={(e) => setMinQualityScore(normalizeInt(e.target.value, 60))}
                    min={0}
                    max={100}
                  />
                </div>

                <div className="flex items-end gap-3">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={strictSubject}
                      onChange={(e) => setStrictSubject(e.target.checked)}
                    />
                    严学科
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="h-4 w-4"
                      checked={dedupByStem}
                      onChange={(e) => setDedupByStem(e.target.checked)}
                    />
                    题干去重
                  </label>
                </div>
              </div>

              <div className="flex gap-2">
                <Button
                  className="flex-1 gap-2"
                  onClick={() => void handleCompose()}
                  disabled={composeBlueprint.isPending}
                >
                  <Sparkles className="h-4 w-4" />
                  {composeBlueprint.isPending ? "生成中..." : "生成题目 ID"}
                </Button>
                <Button variant="outline" className="gap-2" onClick={handleResetSlots}>
                  <Layers className="h-4 w-4" />
                  重置
                </Button>
              </div>
            </CardContent>
          </Card>

          <Card className="shadow-sm">
            <CardHeader className="space-y-1">
              <CardTitle className="flex items-center gap-2 text-base">
                <Layers className="h-4 w-4 text-primary" />
                蓝图槽位
              </CardTitle>
              <CardDescription>每个槽位需要：关键词/知识点 + 数量。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-3">
                {slots.map((s, idx) => (
                  <div key={idx} className="rounded-lg border bg-background/50 p-3 space-y-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-sm font-medium truncate">
                        #{idx + 1} · {slotTitle(s)}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
                        onClick={() => handleRemoveSlot(idx)}
                        disabled={slots.length <= 1}
                        title={slots.length <= 1 ? "至少保留一个槽位" : "移除该槽位"}
                      >
                        删除
                      </Button>
                    </div>

                    <div className="grid gap-2 sm:grid-cols-2">
                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-muted-foreground">关键词</div>
                        <Input
                          value={s.keyword ?? ""}
                          placeholder="例如：阅读理解 / 函数 / 物理实验"
                          onChange={(e) => handleSlotPatch(idx, { keyword: e.target.value })}
                        />
                      </div>
                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-muted-foreground">知识点（可选）</div>
                        <Input
                          value={s.knowledge_point ?? ""}
                          placeholder="例如：二次函数"
                          onChange={(e) => handleSlotPatch(idx, { knowledge_point: e.target.value })}
                        />
                      </div>
                    </div>

                    <div className="grid gap-2 sm:grid-cols-3">
                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-muted-foreground">数量</div>
                        <Input
                          type="number"
                          min={1}
                          max={50}
                          value={s.count}
                          onChange={(e) =>
                            handleSlotPatch(idx, { count: normalizeInt(e.target.value, 0) })
                          }
                        />
                      </div>

                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-muted-foreground">难度</div>
                        <select
                          className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                          value={s.difficulty ?? ""}
                          onChange={(e) => handleSlotPatch(idx, { difficulty: e.target.value })}
                        >
                          <option value="">不限</option>
                          <option value="简单">简单</option>
                          <option value="中等">中等</option>
                          <option value="困难">困难</option>
                        </select>
                      </div>

                      <div className="space-y-1.5">
                        <div className="text-xs font-medium text-muted-foreground">题型</div>
                        {questionTypes.length ? (
                          <select
                            className="h-9 w-full rounded-md border bg-background px-3 text-sm shadow-sm"
                            value={s.question_type ?? ""}
                            onChange={(e) =>
                              handleSlotPatch(idx, { question_type: e.target.value })
                            }
                          >
                            <option value="">不限</option>
                            {questionTypes.map((qt) => (
                              <option key={qt.id} value={qt.name}>
                                {qt.name}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <Input
                            value={s.question_type ?? ""}
                            placeholder="例如：选择题"
                            onChange={(e) =>
                              handleSlotPatch(idx, { question_type: e.target.value })
                            }
                          />
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <Button variant="outline" className="w-full gap-2" onClick={handleAddSlot}>
                <FilePlus2 className="h-4 w-4" />
                添加槽位
              </Button>
            </CardContent>
          </Card>
            </>
          )}
        </motion.section>

        <motion.section
          variants={itemVariants}
          className={cn("min-w-0", rightPanelCollapsed ? "space-y-0" : "space-y-6")}
        >
          {rightPanelCollapsed ? (
            <div className="h-full rounded-lg border bg-background/60 backdrop-blur-sm p-2 flex flex-col items-center gap-2">
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
              <Sparkles className="h-4 w-4 text-primary/70" />
            </div>
          ) : (
          <Card className="shadow-sm">
            <CardHeader className="space-y-0">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 space-y-1">
                  <CardTitle className="flex items-center gap-2 text-base">
                    <Sparkles className="h-4 w-4 text-primary" />
                    结果
                  </CardTitle>
                  <CardDescription>
                    生成成功后会显示题目 ID、分槽位统计与精简预览（不含题干/答案）。
                  </CardDescription>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={() => setRightPanelCollapsed(true)}
                  title="折叠右侧面板"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Badge variant="secondary" className="bg-background/50 backdrop-blur border">
                  总数：{composeResult?.count ?? 0}
                </Badge>
                <Button variant="outline" size="sm" className="h-8 gap-2" onClick={handleCopyIds}>
                  <Clipboard className="h-3.5 w-3.5" />
                  复制题目 ID
                </Button>
              </div>

              <Textarea
                value={toMultilineQuestionIds(questionIds)}
                readOnly
                placeholder="生成后会在这里显示题目 ID..."
                className="min-h-[140px] bg-background font-mono text-xs"
              />

              <Separator />

              <div className="grid gap-3 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">试卷名称</div>
                  <Input value={paperName} onChange={(e) => setPaperName(e.target.value)} />
                </div>
                <div className="flex items-end">
                  <Button
                    className="w-full gap-2"
                    onClick={() => void handleCreatePaper()}
                    disabled={createPaper.isPending || !questionIds.length}
                  >
                    <FilePlus2 className="h-4 w-4" />
                    {createPaper.isPending ? "创建中..." : "创建试卷并保存"}
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
          )}

          {!rightPanelCollapsed ? (
          <Card className="shadow-sm">
            <CardHeader className="space-y-1">
              <CardTitle className="text-base">槽位统计</CardTitle>
              <CardDescription>查看每个槽位命中情况与自动放宽记录。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {sections.length === 0 ? (
                <div className="text-sm text-muted-foreground">暂无数据。</div>
              ) : (
                <div className="space-y-3">
                  {sections.map((sec) => {
                    const title = slotTitle(sec.slot);
                    const requested = normalizeInt(sec.requested, 0);
                    const selected = normalizeInt(sec.selected, 0);
                    const ratio = requested > 0 ? Math.min(1, selected / requested) : 0;

                    return (
                      <div key={sec.index} className="rounded-lg border bg-background/50 p-4 space-y-2">
                        <div className="flex items-center justify-between gap-2">
                          <div className="min-w-0">
                            <div className="text-sm font-medium truncate">
                              #{sec.index + 1} · {title}
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              {sec.success ? "完成" : "失败"} · {selected}/{requested}
                              {sec.error ? ` · ${sec.error}` : ""}
                            </div>
                          </div>
                          <Badge variant={sec.success ? "secondary" : "destructive"}>
                            {sec.success ? "OK" : "ERR"}
                          </Badge>
                        </div>

                        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                          <div
                            className="h-full bg-primary"
                            style={{ width: `${Math.round(ratio * 100)}%` }}
                          />
                        </div>

                        {sec.relax_trace?.length ? (
                          <details className="text-xs">
                            <summary className="cursor-pointer select-none text-muted-foreground hover:text-foreground">
                              查看自动放宽记录（{sec.relax_trace.length} 条）
                            </summary>
                            <pre className="mt-2 rounded bg-muted p-2 text-[10px] overflow-x-auto">
                              {JSON.stringify(sec.relax_trace, null, 2)}
                            </pre>
                          </details>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
          ) : null}

          {!rightPanelCollapsed ? (
          <Card className="shadow-sm">
            <CardHeader className="space-y-1">
              <CardTitle className="text-base">精简预览</CardTitle>
              <CardDescription>只展示元数据与链接，便于快速抽查质量。</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              {preview.length === 0 ? (
                <div className="text-sm text-muted-foreground">暂无预览。</div>
              ) : (
                <div className="space-y-2">
                  {preview.map((q) => {
                    const url = (q.source_url || "").trim();
                    return (
                      <div
                        key={q.question_id}
                        className="rounded-lg border bg-background/50 p-3 flex flex-col gap-2"
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="font-mono text-xs">{q.question_id}</div>
                          <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            {q.type ? <span>{q.type}</span> : null}
                            {q.difficulty ? <span>· {q.difficulty}</span> : null}
                            {typeof q.quality_score === "number" ? (
                              <span>· 质量 {q.quality_score}</span>
                            ) : null}
                          </div>
                        </div>

                        <div className="text-xs text-muted-foreground">
                          {q.source ? <span>{q.source}</span> : <span>来源未知</span>}
                          {q.date ? <span> · {q.date}</span> : null}
                        </div>

                        {url ? (
                          <a
                            href={url}
                            target="_blank"
                            rel="noreferrer"
                            className="text-xs text-primary hover:underline break-all"
                          >
                            {url}
                          </a>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
          ) : null}
        </motion.section>
      </div>
    </motion.div>
  );
}
