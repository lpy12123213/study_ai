import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { format } from "date-fns";
import { ArrowLeft, ChevronLeft, ChevronRight, Download, ExternalLink, Trash2, FileText, CheckCircle2, AlertCircle, Sparkles } from "lucide-react";
import { motion, type Variants } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDeletePaper, useDownloadLink, usePaper } from "@/hooks/usePapers";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { cn } from "@/lib/utils";

function safeString(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  return String(value);
}

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
    },
  },
};

const itemVariants: Variants = {
  hidden: { y: 20, opacity: 0 },
  visible: {
    y: 0,
    opacity: 1,
    transition: {
      type: "spring",
      stiffness: 100,
    },
  },
};

export default function PaperDetailPage() {
  const params = useParams();
  const navigate = useNavigate();

  const paperId = useMemo(() => {
    const raw = params.paperId;
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }, [params.paperId]);

  const paperQuery = usePaper(paperId ?? 0);
  const downloadQuery = useDownloadLink(paperId ?? 0);
  const deletePaper = useDeletePaper();

  const [leftPanelCollapsed, setLeftPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_paper_detail_left_panel_collapsed",
    false,
  );
  const [rightPanelCollapsed, setRightPanelCollapsed] = useLocalStorageState<boolean>(
    "epa_paper_detail_right_panel_collapsed",
    false,
  );

  const handleDelete = async () => {
    if (!paperId) return;
    const ok = window.confirm("确定要删除这份试卷吗？该操作不可撤销。");
    if (!ok) return;
    await deletePaper.mutateAsync(paperId);
    navigate("/papers");
  };

  const handleFetchDownload = async () => {
    if (!paperId) return;
    await downloadQuery.refetch();
  };

  if (!paperId) {
    return (
      <div className="h-full flex items-center justify-center bg-muted/30">
        <Card className="max-w-md w-full">
          <CardContent className="p-8 text-center space-y-4">
            <AlertCircle className="h-10 w-10 text-destructive mx-auto" />
            <div className="text-lg font-semibold">无效的试卷 ID</div>
            <Link to="/papers">
              <Button variant="outline" className="gap-2">
                <ArrowLeft className="h-4 w-4" />
                返回试卷列表
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  const paper = paperQuery.data;
  const questions = paper?.questions ?? [];
  const createdAt = paper?.created_at
    ? format(new Date(paper.created_at), "yyyy-MM-dd HH:mm")
    : "未知";

  return (
    <motion.div 
      className="h-full overflow-y-auto bg-muted/30 p-6 md:p-8"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <motion.div variants={itemVariants} className="flex flex-col md:flex-row items-start justify-between gap-4 mb-8">
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex items-center gap-2 mb-2">
            <Link to="/papers">
                <Button variant="ghost" size="sm" className="h-7 text-muted-foreground hover:text-foreground pl-0 gap-1">
                <ArrowLeft className="h-4 w-4" />
                返回列表
                </Button>
            </Link>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight truncate pr-4">
            {paper?.paper_name || `试卷 #${paperId}`}
          </h1>
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
             <Badge variant="secondary" className="font-normal">ID：{paperId}</Badge>
             <span>创建时间：{createdAt}</span>
             <span>•</span>
             <span>{questions.length} 题</span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="default"
            onClick={() => void handleFetchDownload()}
            disabled={downloadQuery.isFetching}
            className="gap-2 shadow-sm"
          >
            <Download className="h-4 w-4" />
            {downloadQuery.data ? "重新获取链接" : "获取下载链接"}
          </Button>
          <Button
            variant="destructive"
            onClick={() => void handleDelete()}
            disabled={deletePaper.isPending}
            className="gap-2"
          >
            <Trash2 className="h-4 w-4" />
            删除
          </Button>
        </div>
      </motion.div>

      {paperQuery.isLoading ? (
        <div className="flex items-center justify-center h-40">
           <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
      ) : paperQuery.isError ? (
        <div className="rounded-lg border border-destructive/40 bg-destructive/10 p-6 text-destructive flex items-center gap-3">
          <AlertCircle className="h-5 w-5" />
          <span>试卷加载失败：{safeString((paperQuery.error as Error | null)?.message)}</span>
        </div>
      ) : null}

      {paper ? (
        <div
          className={cn(
            "grid gap-6",
            leftPanelCollapsed && rightPanelCollapsed
              ? "lg:grid-cols-[56px_56px]"
              : leftPanelCollapsed
                ? "lg:grid-cols-[56px_1fr]"
                : rightPanelCollapsed
                  ? "lg:grid-cols-[1fr_56px]"
                  : "lg:grid-cols-[2fr_1fr]",
          )}
        >
          {/* Main Question List */}
          <motion.div
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
                  title="展开题目列表"
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
                <div className="h-px w-7 bg-border my-1" />
                <FileText className="h-4 w-4 text-primary/70" />
              </div>
            ) : (
              <Card className="border-none shadow-md">
                <CardHeader className="bg-muted/30 border-b">
                  <div className="flex items-center justify-between gap-2">
                    <CardTitle className="text-lg flex items-center gap-2">
                      <FileText className="h-5 w-5 text-primary" />
                      题目列表
                    </CardTitle>
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="shrink-0">
                        {questions.length} 道题
                      </Badge>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 shrink-0"
                        onClick={() => setLeftPanelCollapsed(true)}
                        title="折叠题目列表"
                      >
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  {questions.length === 0 ? (
                    <div className="p-8 text-center text-muted-foreground">暂无题目数据。</div>
                  ) : (
                    <div className="divide-y">
                      {questions.map((q, idx) => {
                        const qid = q.question_id;
                        const url =
                          q.source_url || (qid ? `https://zujuan.xkw.com/q/${qid}` : "");
                        return (
                          <div
                            key={`${qid}-${idx}`}
                            className="group p-4 hover:bg-muted/30 transition-colors"
                          >
                            <div className="flex items-start justify-between gap-4">
                              <div className="space-y-1 flex-1">
                                <div className="flex items-center gap-2">
                                  <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
                                    {idx + 1}
                                  </span>
                                  <span className="font-mono text-sm text-muted-foreground">ID: {qid}</span>
                                  {q.type && <Badge variant="secondary" className="text-[10px] h-5">{q.type}</Badge>}
                                </div>
                                <div className="pl-8 grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-muted-foreground mt-2">
                                  {q.difficulty && <div>难度：<span className="text-foreground">{q.difficulty}</span></div>}
                                  {q.knowledge_point && <div className="col-span-2 truncate" title={q.knowledge_point}>知识点：<span className="text-foreground">{q.knowledge_point}</span></div>}
                                </div>
                              </div>

                              {url && (
                                <a
                                  href={url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <Button variant="ghost" size="sm" className="h-8 w-8 p-0 opacity-0 group-hover:opacity-100 transition-opacity">
                                    <ExternalLink className="h-4 w-4 text-muted-foreground" />
                                  </Button>
                                </a>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </motion.div>

          {/* Sidebar: Analysis & Download */}
          <motion.div
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
              <>
                {/* Analysis Card */}
                <Card className="overflow-hidden border-none shadow-sm">
                  <CardHeader className="bg-indigo-50/50 dark:bg-indigo-950/10 border-b border-indigo-100 dark:border-indigo-900/20">
                    <div className="flex items-center justify-between gap-2">
                      <CardTitle className="text-base text-indigo-700 dark:text-indigo-400 flex items-center gap-2">
                        <Sparkles className="h-4 w-4" />
                        智能分析
                      </CardTitle>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 shrink-0"
                        onClick={() => setRightPanelCollapsed(true)}
                        title="折叠右侧面板"
                      >
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="p-5">
                    {paper.analysis ? (
                      <div className="space-y-4">
                        <div className="flex items-center justify-between">
                          <span className="text-sm text-muted-foreground">综合难度</span>
                          <div className="flex items-center gap-1">
                            <div className="h-2 w-20 rounded-full bg-muted overflow-hidden">
                              <div
                                className="h-full bg-indigo-500"
                                style={{ width: `${Math.min((paper.analysis.difficulty_score || 0) * 100, 100)}%` }}
                              />
                            </div>
                            <span className="text-sm font-bold text-indigo-600">{paper.analysis.difficulty_score}</span>
                          </div>
                        </div>

                        <div className="rounded-lg bg-muted/30 p-3 text-sm leading-relaxed text-muted-foreground">
                          <span className="block text-xs font-semibold text-foreground mb-1">AI 评语</span>
                          {paper.analysis.ai_comment || "暂无详细评语"}
                        </div>

                        <details className="group">
                          <summary className="cursor-pointer select-none text-xs text-muted-foreground flex items-center gap-1 hover:text-foreground">
                            <div className="h-px bg-border flex-1" />
                            <span>查看雷达数据</span>
                            <div className="h-px bg-border flex-1" />
                          </summary>
                          <pre className="mt-2 rounded bg-muted p-2 text-[10px] overflow-x-auto">
                            {JSON.stringify(paper.analysis.radar_data, null, 2)}
                          </pre>
                        </details>
                      </div>
                    ) : (
                      <div className="text-sm text-muted-foreground py-2 text-center">
                        暂无分析数据
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* Download Card */}
                <Card className="overflow-hidden border-none shadow-sm">
                  <CardHeader className="bg-emerald-50/50 dark:bg-emerald-950/10 border-b border-emerald-100 dark:border-emerald-900/20">
                    <CardTitle className="text-base text-emerald-700 dark:text-emerald-400 flex items-center gap-2">
                      <Download className="h-4 w-4" />
                      下载资源
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="p-5">
                    {downloadQuery.isFetching ? (
                      <div className="flex flex-col items-center justify-center py-4 space-y-2">
                        <div className="animate-spin h-5 w-5 border-2 border-emerald-500 border-t-transparent rounded-full" />
                        <p className="text-xs text-muted-foreground">正在生成链接...</p>
                      </div>
                    ) : downloadQuery.data ? (
                      <div className="space-y-4 animate-in fade-in slide-in-from-bottom-2">
                        <div className="flex items-center gap-2 text-sm text-emerald-600 font-medium">
                          <CheckCircle2 className="h-4 w-4" />
                          链接已生成
                        </div>

                        <div className="space-y-2">
                          {downloadQuery.data.question_links.map((url, idx) => (
                            <a
                              key={idx}
                              href={url}
                              target="_blank"
                              rel="noreferrer"
                              className="flex items-center gap-2 rounded-md border p-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors truncate"
                              title={url}
                            >
                              <ExternalLink className="h-3 w-3 shrink-0" />
                              <span className="truncate">{url}</span>
                            </a>
                          ))}
                        </div>

                        <div className="text-[10px] text-muted-foreground bg-muted/30 p-2 rounded">
                          <ol className="list-decimal list-inside space-y-0.5">
                            {downloadQuery.data.instructions.map((s, idx) => (
                              <li key={idx}>{s}</li>
                            ))}
                          </ol>
                        </div>
                      </div>
                    ) : (
                      <div className="text-center py-4">
                        <p className="text-sm text-muted-foreground mb-3">
                          生成组卷网的题目下载链接
                        </p>
                        <Button
                          size="sm"
                          className="w-full bg-emerald-600 hover:bg-emerald-700 text-white"
                          onClick={() => void handleFetchDownload()}
                        >
                          生成链接
                        </Button>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </motion.div>
        </div>
      ) : null}
    </motion.div>
  );
}
