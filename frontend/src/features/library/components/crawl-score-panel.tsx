import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ClipboardCheck, CloudDownload, StopCircle } from "lucide-react";
import { crawlLibrary, scoreLibrary } from "@/features/question-library/api";
import { DEFAULT_SUBJECT, DIFFICULTIES, EDU_LEVELS, QUESTION_TYPES, SUBJECTS } from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { clamp } from "@/lib/format";
import { SubjectSelect } from "@/components/question/subject-select";
import { TaskProgressPanel } from "@/components/task/task-progress-panel";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useTaskStream } from "../model/use-task-stream";


// ---------------- 抓取与评分 ----------------

export function CrawlScorePanel() {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  const crawlStream = useTaskStream("question_library_crawl");
  const scoreStream = useTaskStream("question_library_score");
  const [crawlOpen, setCrawlOpen] = useState(false);
  const [scoreOpen, setScoreOpen] = useState(false);
  const [crawlForm, setCrawlForm] = useState({
    query: "",
    subject: "all",
    eduLevel: "all",
    difficulty: "all",
    questionType: "all",
    limit: 30,
    maxPages: 2,
    minQuality: 0,
  });
  const [scoreForm, setScoreForm] = useState({
    subject: DEFAULT_SUBJECT as string,
    limit: 50,
    onlyUnscored: true,
  });

  const setCrawl = <K extends keyof typeof crawlForm>(key: K, value: (typeof crawlForm)[K]) =>
    setCrawlForm((f) => ({ ...f, [key]: value }));
  const setScore = <K extends keyof typeof scoreForm>(key: K, value: (typeof scoreForm)[K]) =>
    setScoreForm((f) => ({ ...f, [key]: value }));

  const submitCrawl = () => {
    const query = crawlForm.query.trim();
    if (!query) {
      toast({ title: "请填写抓取关键词", variant: "warning" });
      return;
    }
    crawlStream.start(
      `抓取：${query}`,
      (handlers) =>
        crawlLibrary(
          {
            query,
            subject: crawlForm.subject === "all" ? "" : crawlForm.subject,
            edu_level: crawlForm.eduLevel === "all" ? "" : crawlForm.eduLevel,
            difficulty: crawlForm.difficulty === "all" ? "" : crawlForm.difficulty,
            question_type: crawlForm.questionType === "all" ? "" : crawlForm.questionType,
            limit: clamp(Math.round(crawlForm.limit) || 30, 1, 200),
            max_pages: clamp(Math.round(crawlForm.maxPages) || 2, 1, 50),
            min_quality_score: clamp(Math.round(crawlForm.minQuality) || 0, 0, 100),
          },
          handlers,
        ),
      {
        onDoneEvent: (data) => {
          toast({
            title: "抓取完成",
            description: `已入库 ${Number(data?.inserted ?? data?.count ?? 0)} 题`,
            variant: "success",
          });
          queryClient.invalidateQueries({ queryKey: ["library-items"] });
        },
      },
    );
  };

  const submitScore = () => {
    if (!scoreForm.subject) {
      toast({ title: "请选择学科", variant: "warning" });
      return;
    }
    scoreStream.start(
      `${scoreForm.subject} 评分`,
      (handlers) =>
        scoreLibrary(
          {
            subject: scoreForm.subject,
            limit: clamp(Math.round(scoreForm.limit) || 50, 1, 500),
            only_unscored: scoreForm.onlyUnscored,
          },
          handlers,
        ),
      {
        onDoneEvent: (data) => {
          const scored = Number(data?.scored ?? data?.count ?? 0);
          const hidden = Number(data?.hidden ?? 0);
          toast({
            title: "评分完成",
            description: `已评分 ${scored} 题${hidden > 0 ? `，自动隐藏低分 ${hidden} 题` : ""}`,
            variant: "success",
          });
          queryClient.invalidateQueries({ queryKey: ["library-items"] });
        },
      },
    );
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <CloudDownload className="size-4 text-primary" />
              题库抓取
            </CardTitle>
            <CardDescription>从组卷网按关键词抓取题目并写入本地题库</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setCrawlOpen(true)}>
              <CloudDownload />
              开始抓取
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardCheck className="size-4 text-primary" />
              AI 评分清洗
            </CardTitle>
            <CardDescription>为题库题目批量 AI 评分，低分题自动隐藏</CardDescription>
          </CardHeader>
          <CardContent>
            <Button onClick={() => setScoreOpen(true)}>
              <ClipboardCheck />
              开始评分
            </Button>
          </CardContent>
        </Card>
      </div>

      <Dialog open={crawlOpen} onOpenChange={setCrawlOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>题库抓取</DialogTitle>
            <DialogDescription>按关键词从组卷网检索题目并解析入库，过程可实时观察</DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            <div className="space-y-1.5">
              <Label>关键词（必填）</Label>
              <Input
                value={crawlForm.query}
                onChange={(e) => setCrawl("query", e.target.value)}
                placeholder="例如：二次函数最值"
              />
            </div>
            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <Label>学科</Label>
                <Select value={crawlForm.subject} onValueChange={(v) => setCrawl("subject", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    {SUBJECTS.map((s) => (
                      <SelectItem key={s} value={s}>
                        {s}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>学段</Label>
                <Select value={crawlForm.eduLevel} onValueChange={(v) => setCrawl("eduLevel", v)}>
                  <SelectTrigger>
                    <SelectValue placeholder="不限" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">不限</SelectItem>
                    {EDU_LEVELS.map((l) => (
                      <SelectItem key={l} value={l}>
                        {l}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>难度</Label>
                <Select value={crawlForm.difficulty} onValueChange={(v) => setCrawl("difficulty", v)}>
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
                <Select value={crawlForm.questionType} onValueChange={(v) => setCrawl("questionType", v)}>
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
                <Label>抓取数量（1-200）</Label>
                <Input
                  type="number"
                  min={1}
                  max={200}
                  value={crawlForm.limit}
                  onChange={(e) => setCrawl("limit", Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>最大页数（1-50）</Label>
                <Input
                  type="number"
                  min={1}
                  max={50}
                  value={crawlForm.maxPages}
                  onChange={(e) => setCrawl("maxPages", Number(e.target.value))}
                />
              </div>
              <div className="space-y-1.5">
                <Label>最低质量分（0-100）</Label>
                <Input
                  type="number"
                  min={0}
                  max={100}
                  value={crawlForm.minQuality}
                  onChange={(e) => setCrawl("minQuality", Number(e.target.value))}
                />
              </div>
            </div>
            {crawlStream.taskId ? <TaskProgressPanel taskId={crawlStream.taskId} /> : null}
          </div>
          <DialogFooter>
            {crawlStream.running ? (
              <Button variant="outline" onClick={crawlStream.stop}>
                <StopCircle />
                停止
              </Button>
            ) : null}
            <Button onClick={submitCrawl} disabled={crawlStream.running}>
              {crawlStream.running ? <Spinner className="text-primary-foreground" /> : <CloudDownload />}
              {crawlStream.running ? "抓取中…" : "开始抓取"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={scoreOpen} onOpenChange={setScoreOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>AI 评分清洗</DialogTitle>
            <DialogDescription>按学科批量评分题库题目，低分题将被自动隐藏</DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>学科（必填）</Label>
              <SubjectSelect value={scoreForm.subject} onValueChange={(v) => setScore("subject", v)} />
            </div>
            <div className="space-y-1.5">
              <Label>评分数量上限</Label>
              <Input
                type="number"
                min={1}
                max={500}
                value={scoreForm.limit}
                onChange={(e) => setScore("limit", Number(e.target.value))}
              />
            </div>
            <label className="flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5">
              <span className="text-sm">仅评未评分题目</span>
              <Switch checked={scoreForm.onlyUnscored} onCheckedChange={(v) => setScore("onlyUnscored", v)} />
            </label>
            {scoreStream.taskId ? <TaskProgressPanel taskId={scoreStream.taskId} /> : null}
          </div>
          <DialogFooter>
            {scoreStream.running ? (
              <Button variant="outline" onClick={scoreStream.stop}>
                <StopCircle />
                停止
              </Button>
            ) : null}
            <Button onClick={submitScore} disabled={scoreStream.running}>
              {scoreStream.running ? <Spinner className="text-primary-foreground" /> : <ClipboardCheck />}
              {scoreStream.running ? "评分中…" : "开始评分"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

