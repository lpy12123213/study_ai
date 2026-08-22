import { useMemo, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { AlertCircle, Braces, CheckCircle2, FilePlus2, Upload } from "lucide-react";

import { libraryApi } from "@/features/question-library/api";
import { useUiStore } from "@/stores/ui";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorText } from "../model/shared";
import { parseGaokaoImportText, preflightGaokaoImport } from "../model/gaokao-import";

const EMPTY_FORM = {
  question_id: "",
  subject: "高中数学",
  stem: "",
  answer: "",
  analysis: "",
  exam_year: String(new Date().getFullYear()),
  region: "",
  paper_name: "",
  paper_variant: "",
  question_number: "",
  source_url: "",
};

type ManualForm = typeof EMPTY_FORM;

function candidateLabel(candidate: Record<string, unknown>, index: number): string {
  const questionNumber = String((candidate.source as Record<string, unknown> | undefined)?.question_number ?? "").trim();
  return questionNumber ? `第 ${questionNumber} 题` : `第 ${index + 1} 条`;
}

export function GaokaoImportSheet({
  open,
  onOpenChange,
  onImported,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: () => void;
}) {
  const toast = useUiStore((state) => state.toast);
  const [mode, setMode] = useState("json");
  const [jsonText, setJsonText] = useState("");
  const [manualForm, setManualForm] = useState<ManualForm>(EMPTY_FORM);
  const [manualItems, setManualItems] = useState<Record<string, unknown>[]>([]);
  const [manualError, setManualError] = useState("");

  const parsed = useMemo(() => {
    if (mode !== "json") return { candidates: manualItems, parseError: "" };
    try {
      return { candidates: parseGaokaoImportText(jsonText), parseError: "" };
    } catch (error) {
      return { candidates: [], parseError: error instanceof Error ? error.message : "JSON 无法解析" };
    }
  }, [jsonText, manualItems, mode]);
  const preflight = useMemo(() => preflightGaokaoImport(parsed.candidates), [parsed.candidates]);
  const importMutation = useMutation({
    mutationFn: () => libraryApi.importGaokao(preflight.validItems),
    onSuccess: (result) => {
      toast({ title: "高考真题导入完成", description: `已写入 ${result.upserted} 题`, variant: "success" });
      onImported();
      onOpenChange(false);
    },
  });

  const updateManual = (key: keyof ManualForm, value: string) => {
    setManualForm((current) => ({ ...current, [key]: value }));
    setManualError("");
  };
  const addManualItem = () => {
    const candidate = {
      question_id: manualForm.question_id,
      subject: manualForm.subject,
      stem: manualForm.stem,
      answer: manualForm.answer,
      analysis: manualForm.analysis,
      origin: "media",
      source: {
        exam_year: Number(manualForm.exam_year),
        region: manualForm.region,
        paper_name: manualForm.paper_name,
        paper_variant: manualForm.paper_variant,
        question_number: manualForm.question_number,
        source_url: manualForm.source_url,
        verified: false,
      },
    };
    const check = preflightGaokaoImport([...manualItems, candidate]);
    const newIssues = check.issues.filter((issue) => issue.index === manualItems.length);
    if (newIssues.length > 0) {
      setManualError(newIssues.map((issue) => issue.message).join("；"));
      return;
    }
    setManualItems((items) => [...items, candidate]);
    setManualForm((current) => ({ ...EMPTY_FORM, subject: current.subject, exam_year: current.exam_year }));
  };

  const grouped = useMemo(() => {
    const groups = new Map<string, { title: string; entries: { candidate: Record<string, unknown>; index: number }[] }>();
    parsed.candidates.forEach((candidate, index) => {
      const source = (candidate.source as Record<string, unknown> | undefined) ?? {};
      const title = [source.exam_year, source.region, source.paper_name, source.paper_variant]
        .map((value) => String(value ?? "").trim())
        .filter(Boolean)
        .join(" · ") || "出处未完成";
      const key = title;
      const group = groups.get(key) ?? { title, entries: [] };
      group.entries.push({ candidate, index });
      groups.set(key, group);
    });
    return Array.from(groups.values());
  }, [parsed.candidates]);

  const importDisabled =
    importMutation.isPending ||
    Boolean(parsed.parseError) ||
    preflight.validItems.length === 0 ||
    preflight.issues.length > 0;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-full max-w-2xl flex-col gap-0 p-0 sm:max-w-2xl">
        <SheetHeader className="shrink-0 border-b border-border px-5 py-4">
          <SheetTitle>导入高考真题</SheetTitle>
          <SheetDescription>年份、地区和试卷名必须完整；公式保留 LaTeX，图片保留在题干原始位置。</SheetDescription>
        </SheetHeader>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <Tabs value={mode} onValueChange={setMode}>
            <TabsList>
              <TabsTrigger value="json"><Braces />粘贴 JSON</TabsTrigger>
              <TabsTrigger value="manual"><FilePlus2 />逐题录入</TabsTrigger>
            </TabsList>
            <TabsContent value="json" className="space-y-2">
              <Textarea
                value={jsonText}
                onChange={(event) => setJsonText(event.target.value)}
                placeholder='粘贴题目数组，或 { "items": [...] }'
                className="min-h-56 font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">题干、答案和解析中的 \(...\)、\[...\]、$...$ 将按 LaTeX 渲染。</p>
            </TabsContent>
            <TabsContent value="manual" className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input value={manualForm.question_id} onChange={(event) => updateManual("question_id", event.target.value)} placeholder="question_id *" />
                <Input value={manualForm.subject} onChange={(event) => updateManual("subject", event.target.value)} placeholder="学科 *" />
                <Input value={manualForm.exam_year} onChange={(event) => updateManual("exam_year", event.target.value)} inputMode="numeric" placeholder="年份 *" />
                <Input value={manualForm.region} onChange={(event) => updateManual("region", event.target.value)} placeholder="地区 *" />
                <Input value={manualForm.paper_name} onChange={(event) => updateManual("paper_name", event.target.value)} placeholder="试卷名 *" className="sm:col-span-2" />
                <Input value={manualForm.paper_variant} onChange={(event) => updateManual("paper_variant", event.target.value)} placeholder="卷别" />
                <Input value={manualForm.question_number} onChange={(event) => updateManual("question_number", event.target.value)} placeholder="题号" />
                <Input value={manualForm.source_url} onChange={(event) => updateManual("source_url", event.target.value)} placeholder="来源链接" className="sm:col-span-2" />
              </div>
              <Textarea value={manualForm.stem} onChange={(event) => updateManual("stem", event.target.value)} placeholder="题干（支持 LaTeX 与原位图片 HTML）*" className="min-h-28" />
              <Textarea value={manualForm.answer} onChange={(event) => updateManual("answer", event.target.value)} placeholder="答案（支持 LaTeX）" />
              <Textarea value={manualForm.analysis} onChange={(event) => updateManual("analysis", event.target.value)} placeholder="解析（支持 LaTeX）" />
              {manualError ? <p className="text-xs text-destructive">{manualError}</p> : null}
              <Button type="button" variant="outline" onClick={addManualItem}><FilePlus2 />加入预览</Button>
            </TabsContent>
          </Tabs>

          {parsed.parseError ? (
            <Alert variant="destructive"><AlertCircle /><AlertTitle>JSON 无法预检</AlertTitle><AlertDescription>{parsed.parseError}</AlertDescription></Alert>
          ) : null}
          {preflight.issues.length > 0 ? (
            <Alert variant="warning">
              <AlertCircle />
              <AlertTitle>{preflight.issues.length} 处需要修正</AlertTitle>
              <AlertDescription>{preflight.issues.slice(0, 5).map((issue) => `第 ${issue.index + 1} 条：${issue.message}`).join("；")}</AlertDescription>
            </Alert>
          ) : null}

          {grouped.length > 0 ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge variant="secondary">共 {parsed.candidates.length} 题</Badge>
                <Badge variant="success">通过 {preflight.validItems.length} 题</Badge>
                {preflight.issues.length > 0 ? <Badge variant="warning">待修正 {preflight.issues.length} 处</Badge> : null}
              </div>
              {grouped.map((group) => (
                <Card key={group.title}>
                  <CardHeader className="py-3"><CardTitle className="text-sm">{group.title}</CardTitle></CardHeader>
                  <CardContent className="space-y-2 pb-3">
                    {group.entries.map(({ candidate, index }) => {
                      const hasIssue = preflight.issues.some((issue) => issue.index === index);
                      return (
                        <div key={`${String(candidate.question_id ?? "item")}-${index}`} className="flex items-start justify-between gap-3 border-t border-border/60 pt-2 text-xs first:border-0 first:pt-0">
                          <div className="min-w-0"><div className="font-medium">{candidateLabel(candidate, index)}</div><div className="truncate text-muted-foreground">{String(candidate.stem ?? "题干缺失")}</div></div>
                          <Badge variant={hasIssue ? "warning" : "success"}>{hasIssue ? "待修正" : "通过"}</Badge>
                        </div>
                      );
                    })}
                  </CardContent>
                </Card>
              ))}
            </div>
          ) : null}

          {importMutation.isError ? (
            <Alert variant="destructive"><AlertCircle /><AlertTitle>导入失败，输入已保留</AlertTitle><AlertDescription>{apiErrorText(importMutation.error, "请根据具体条目修正后重试")}</AlertDescription></Alert>
          ) : null}
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-border px-5 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
          <Button disabled={importDisabled} onClick={() => importMutation.mutate()}>
            {importMutation.isPending ? <Spinner /> : preflight.issues.length === 0 && preflight.validItems.length > 0 ? <CheckCircle2 /> : <Upload />}
            确认导入 {preflight.validItems.length} 题
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
