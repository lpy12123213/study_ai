import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { Plus, Trash2, ExternalLink, FileText, FilePlus2, Sparkles } from "lucide-react";
import { motion, type Variants } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useCreatePaper, useDeletePaper, usePapers } from "@/hooks/usePapers";

function parseQuestionIds(raw: string): string[] {
  const parts = raw
    .split(/[\s,，;；]+/g)
    .map((s) => s.trim())
    .filter(Boolean);
  return Array.from(new Set(parts));
}

const containerVariants: Variants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.05,
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

export default function PapersPage() {
  const navigate = useNavigate();
  const papersQuery = usePapers();
  const deletePaper = useDeletePaper();
  const createPaper = useCreatePaper();

  const [paperName, setPaperName] = useState("");
  const [questionIdsRaw, setQuestionIdsRaw] = useState("");

  const questionIds = useMemo(
    () => parseQuestionIds(questionIdsRaw),
    [questionIdsRaw],
  );

  const handleCreate = async () => {
    const name = paperName.trim();
    if (!name) {
      window.alert("请填写试卷名称。");
      return;
    }
    if (questionIds.length === 0) {
      window.alert("请至少填写一个题目 ID。");
      return;
    }

    const res = await createPaper.mutateAsync({
      paperName: name,
      questionIds,
    });
    setPaperName("");
    setQuestionIdsRaw("");
    navigate(`/papers/${res.paper_id}`);
  };

  const handleDelete = async (paperId: number) => {
    const ok = window.confirm("确定要删除这份试卷吗？该操作不可撤销。");
    if (!ok) return;
    await deletePaper.mutateAsync(paperId);
  };

  const papers = papersQuery.data ?? [];

  return (
    <motion.div 
      className="h-full overflow-y-auto bg-muted/30 p-6 md:p-8"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">试卷库</h1>
          <p className="text-muted-foreground mt-1">
            查看、管理通过 AI 或接口保存的试卷
          </p>
        </div>

        <Badge variant="secondary" className="px-3 py-1 text-sm bg-background/50 backdrop-blur border">
          共 {papersQuery.isLoading ? "..." : papers.length} 份试卷
        </Badge>
      </div>

      <div className="grid gap-6 lg:grid-cols-3 xl:grid-cols-4">
        {/* Creation Card */}
        <motion.div variants={itemVariants} className="lg:col-span-1">
          <Card className="sticky top-6 border-dashed border-2 shadow-none hover:border-primary/50 transition-colors bg-muted/30">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <FilePlus2 className="h-5 w-5 text-primary" />
                手动创建
              </CardTitle>
              <CardDescription>
                已有题目 ID？直接创建试卷
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  试卷名称
                </label>
                <Input
                  value={paperName}
                  onChange={(e) => setPaperName(e.target.value)}
                  placeholder="例如：高一数学专项练习"
                  className="bg-background"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none">
                  题目 ID 列表
                </label>
                <Textarea
                  value={questionIdsRaw}
                  onChange={(e) => setQuestionIdsRaw(e.target.value)}
                  placeholder="ID 之间用空格或换行分隔..."
                  className="min-h-[120px] bg-background font-mono text-xs resize-none"
                />
                <div className="flex justify-between items-center text-xs text-muted-foreground">
                    <span>支持批量粘贴</span>
                    <span className={questionIds.length > 0 ? "text-primary font-medium" : ""}>
                       已识别: {questionIds.length}
                    </span>
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex-col gap-3 pt-0">
              <Button
                onClick={() => void handleCreate()}
                disabled={createPaper.isPending}
                className="w-full gap-2 shadow-md"
              >
                <Plus className="h-4 w-4" />
                立即创建
              </Button>
               <div className="text-[10px] text-center text-muted-foreground/70">
                 提示: AI 对话可以自动帮您检索并填写 ID
               </div>
            </CardFooter>
          </Card>
        </motion.div>

        {/* Papers List */}
        <div className="lg:col-span-2 xl:col-span-3">
          {papersQuery.isLoading ? (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, i) => (
                <Card key={i} className="animate-pulse shadow-sm border-transparent bg-background/50">
                  <div className="p-5 space-y-3">
                    <div className="h-4 w-2/3 rounded bg-muted" />
                    <div className="h-3 w-1/3 rounded bg-muted" />
                    <div className="h-20 w-full rounded bg-muted/50 mt-4" />
                  </div>
                </Card>
              ))}
            </div>
          ) : papers.length === 0 ? (
            <motion.div 
                initial={{ opacity: 0, scale: 0.95 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex flex-col items-center justify-center h-[400px] rounded-xl border border-dashed bg-muted/10"
            >
               <div className="h-16 w-16 rounded-full bg-muted flex items-center justify-center mb-4">
                  <FileText className="h-8 w-8 text-muted-foreground/50" />
               </div>
               <h3 className="text-lg font-medium">暂无试卷</h3>
               <p className="text-sm text-muted-foreground max-w-sm text-center mt-2 mb-6">
                 您的试卷库是空的。尝试在左侧手动创建，或者去 AI 对话页面让助手帮您组卷。
               </p>
               <Link to="/chat">
                  <Button className="gap-2">
                    <Sparkles className="h-4 w-4" />
                    去 AI 对话
                  </Button>
               </Link>
            </motion.div>
          ) : (
            <motion.div 
                className="grid gap-4 md:grid-cols-2 lg:grid-cols-2 xl:grid-cols-3"
                variants={containerVariants}
            >
              {papers.map((p) => {
                const createdAt = p.created_at
                  ? format(new Date(p.created_at), "yyyy-MM-dd")
                  : "未知";
                const count = p.question_count ?? 0;
                return (
                  <motion.div key={p.paper_id} variants={itemVariants}>
                      <Card className="group relative overflow-hidden transition-all hover:shadow-lg hover:border-primary/30 h-full flex flex-col">
                        <CardHeader className="pb-3">
                          <div className="flex justify-between items-start gap-2">
                             <div className="p-2 rounded-lg bg-primary/5 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                                <FileText className="h-5 w-5" />
                             </div>
                             <Badge variant="outline" className="font-normal text-xs">{count} 题</Badge>
                          </div>
                          <CardTitle className="text-base font-semibold leading-tight line-clamp-2 mt-2 group-hover:text-primary transition-colors">
                             {p.paper_name}
                          </CardTitle>
                          <CardDescription className="text-xs flex items-center gap-1 mt-1">
                             <span className="tabular-nums">#{p.paper_id}</span>
                             <span>·</span>
                             <span>{createdAt}</span>
                          </CardDescription>
                        </CardHeader>
                        
                        <CardFooter className="mt-auto pt-3 border-t bg-muted/10 flex gap-2">
                            <Link to={`/papers/${p.paper_id}`} className="flex-1">
                                <Button variant="ghost" size="sm" className="w-full text-xs h-8 hover:bg-background shadow-sm hover:shadow">
                                   <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                                   详情
                                </Button>
                            </Link>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-8 w-8 px-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                              onClick={() => void handleDelete(p.paper_id)}
                              disabled={deletePaper.isPending}
                              title="删除试卷"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </Button>
                        </CardFooter>
                      </Card>
                  </motion.div>
                );
              })}
            </motion.div>
          )}
        </div>
      </div>
    </motion.div>
  );
}
