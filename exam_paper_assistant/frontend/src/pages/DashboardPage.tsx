import { Link } from "react-router-dom";
import { format } from "date-fns";
import {
  FileText,
  MessagesSquare,
  Sparkles,
  ArrowRight,
  Activity,
  Clock,
  BookOpen,
  Layers
} from "lucide-react";
import { motion, type Variants } from "framer-motion";

import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useConversations } from "@/hooks/useChat";
import { usePapers } from "@/hooks/usePapers";
import { useHealth } from "@/hooks/useSystem";

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

export default function DashboardPage() {
  const healthQuery = useHealth();
  const conversationsQuery = useConversations();
  const papersQuery = usePapers();

  const papers = papersQuery.data ?? [];
  const conversations = conversationsQuery.data ?? [];

  const backendStatus = healthQuery.isLoading
    ? "checking"
    : healthQuery.isError
    ? "offline"
    : "online";

  const recentPapers = papers.slice(0, 5);

  return (
    <motion.div
      className="h-full overflow-y-auto bg-muted/30 p-6 md:p-8"
      variants={containerVariants}
      initial="hidden"
      animate="visible"
    >
      {/* Hero Section */}
      <motion.div variants={itemVariants} className="mb-8 flex flex-col justify-between gap-6 md:flex-row md:items-end">
        <div>
           <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground mb-2">
            <span className="relative flex h-2.5 w-2.5">
              <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${backendStatus === 'online' ? 'bg-emerald-400' : 'bg-red-400'}`}></span>
              <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${backendStatus === 'online' ? 'bg-emerald-500' : backendStatus === 'offline' ? 'bg-red-500' : 'bg-amber-500'}`}></span>
            </span>
            <span>系统状态: {backendStatus === "online" ? "正常运行" : backendStatus === "offline" ? "服务离线" : "连接中..."}</span>
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight lg:text-5xl bg-gradient-to-r from-primary to-primary/60 bg-clip-text text-transparent">
            欢迎回来, 老师
          </h1>
          <p className="mt-2 max-w-2xl text-lg text-muted-foreground">
            准备好开始今天的组卷工作了吗？AI 助手已就绪。
          </p>
        </div>
        <div className="flex gap-3">
          <Link to="/chat">
            <Button size="lg" className="gap-2 shadow-lg shadow-primary/20 hover:shadow-primary/30 transition-all">
              <Sparkles className="h-5 w-5" />
              立即组卷
            </Button>
          </Link>
          <Link to="/blueprint">
            <Button variant="secondary" size="lg" className="gap-2">
              <Layers className="h-5 w-5" />
              蓝图组卷
            </Button>
          </Link>
          <Link to="/papers">
            <Button variant="outline" size="lg" className="gap-2">
              <FileText className="h-5 w-5" />
              查看试卷
            </Button>
          </Link>
        </div>
      </motion.div>

      {/* Stats Grid */}
      <motion.div variants={itemVariants} className="grid gap-6 md:grid-cols-2 lg:grid-cols-3 mb-8">
        <Link to="/chat">
            <Card className="group relative overflow-hidden border-none shadow-md hover:shadow-xl transition-all duration-300 bg-gradient-to-br from-blue-50 to-white dark:from-blue-950/20 dark:to-background">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">活跃对话</CardTitle>
                <MessagesSquare className="h-4 w-4 text-primary group-hover:scale-110 transition-transform" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{conversationsQuery.isLoading ? "-" : conversations.length}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  正在进行的组卷任务
                </p>
                <div className="absolute -bottom-4 -right-4 h-24 w-24 rounded-full bg-primary/5 blur-2xl group-hover:bg-primary/10 transition-colors" />
              </CardContent>
            </Card>
        </Link>

        <Link to="/papers">
            <Card className="group relative overflow-hidden border-none shadow-md hover:shadow-xl transition-all duration-300 bg-gradient-to-br from-indigo-50 to-white dark:from-indigo-950/20 dark:to-background">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">已存试卷</CardTitle>
                <BookOpen className="h-4 w-4 text-indigo-500 group-hover:scale-110 transition-transform" />
              </CardHeader>
              <CardContent>
                <div className="text-3xl font-bold">{papersQuery.isLoading ? "-" : papers.length}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  本地保存的试卷库
                </p>
                <div className="absolute -bottom-4 -right-4 h-24 w-24 rounded-full bg-indigo-500/5 blur-2xl group-hover:bg-indigo-500/10 transition-colors" />
              </CardContent>
            </Card>
        </Link>

         <Card className="group relative overflow-hidden border-none shadow-md bg-gradient-to-br from-amber-50 to-white dark:from-amber-950/20 dark:to-background">
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">快速提示</CardTitle>
            <Sparkles className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
               <div className="flex items-center text-sm">
                  <Badge variant="secondary" className="mr-2 text-xs bg-white/50 dark:bg-black/20">Tips</Badge>
                  <span className="truncate text-muted-foreground">对话页勾选"显示工具调用"可看详情</span>
               </div>
               <div className="flex items-center text-sm">
                  <Badge variant="secondary" className="mr-2 text-xs bg-white/50 dark:bg-black/20">Hot</Badge>
                  <span className="truncate text-muted-foreground">试试 "高一函数中等难度"</span>
               </div>
            </div>
             <div className="absolute -bottom-4 -right-4 h-24 w-24 rounded-full bg-amber-500/5 blur-2xl transition-colors" />
          </CardContent>
        </Card>
      </motion.div>

      {/* Main Content Split */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Recent Papers */}
        <motion.div variants={itemVariants} className="lg:col-span-2">
          <Card className="h-full shadow-sm border-muted/60">
            <CardHeader className="flex flex-row items-center justify-between">
              <div>
                  <CardTitle>最近试卷</CardTitle>
                  <CardDescription>最近创建和编辑的试卷记录</CardDescription>
              </div>
              <Link to="/papers">
                <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground hover:text-primary">
                  查看全部 <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </CardHeader>
            <CardContent>
              {papersQuery.isLoading ? (
                 <div className="flex h-32 items-center justify-center text-muted-foreground animate-pulse">
                    加载数据中...
                 </div>
              ) : recentPapers.length === 0 ? (
                <div className="flex h-48 flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-muted-foreground bg-muted/20">
                  <FileText className="h-8 w-8 opacity-50" />
                  <p>暂无试卷记录</p>
                  <Link to="/chat">
                    <Button variant="link">去创建第一份试卷</Button>
                  </Link>
                </div>
              ) : (
                <div className="space-y-4">
                  {recentPapers.map((p, i) => (
                    <motion.div
                      key={p.paper_id}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.05 }}
                      className="group flex items-center justify-between rounded-xl border p-3 hover:bg-muted/50 transition-colors hover:border-primary/20"
                    >
                      <div className="flex items-center gap-4">
                        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary group-hover:bg-primary group-hover:text-primary-foreground transition-colors">
                          <FileText className="h-5 w-5" />
                        </div>
                        <div>
                          <div className="font-medium group-hover:text-primary transition-colors">{p.paper_name}</div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                            <Clock className="h-3 w-3" />
                            {p.created_at
                              ? format(new Date(p.created_at), "yyyy-MM-dd HH:mm")
                              : "未知时间"}
                            <span className="text-muted-foreground/50">•</span>
                            <span>{p.question_count ?? 0} 题</span>
                          </div>
                        </div>
                      </div>
                      <Link to={`/papers/${p.paper_id}`}>
                        <Button variant="ghost" size="icon" className="opacity-0 group-hover:opacity-100 transition-opacity">
                            <ArrowRight className="h-4 w-4" />
                        </Button>
                      </Link>
                    </motion.div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>

        {/* System Health / Secondary Info */}
        <motion.div variants={itemVariants} className="space-y-6">
            <Card className="shadow-sm border-muted/60">
                <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                        <Activity className="h-5 w-5 text-muted-foreground" />
                        后端连接详情
                    </CardTitle>
                </CardHeader>
                <CardContent>
                     {healthQuery.isError ? (
                        <div className="rounded-lg bg-destructive/10 p-4 text-sm text-destructive">
                             <p className="font-semibold mb-1">连接失败</p>
                             <p className="opacity-90">{(healthQuery.error as Error).message}</p>
                             <div className="mt-3 text-xs bg-background/50 p-2 rounded">
                                提示: 请确保后端服务已启动 (Port 8000)
                             </div>
                        </div>
                     ) : (
                        <div className="space-y-4">
                            <div className="flex items-center justify-between text-sm">
                                <span className="text-muted-foreground">服务名称</span>
                                <span className="font-medium">{healthQuery.data?.service || "-"}</span>
                            </div>
                             <div className="flex items-center justify-between text-sm">
                                <span className="text-muted-foreground">状态</span>
                                <span className="inline-flex items-center rounded-full bg-emerald-500/10 px-2 py-1 text-xs font-medium text-emerald-600 ring-1 ring-inset ring-emerald-500/20">
                                    {healthQuery.data?.status || "未知"}
                                </span>
                            </div>
                            <div className="h-px bg-border" />
                            <div className="text-xs text-muted-foreground text-center">
                                系统运行平稳
                            </div>
                        </div>
                     )}
                </CardContent>
            </Card>

            <Card className="bg-primary text-primary-foreground shadow-lg overflow-hidden relative">
                <CardHeader>
                    <CardTitle>需要帮助？</CardTitle>
                    <CardDescription className="text-primary-foreground/80">查看文档或联系支持</CardDescription>
                </CardHeader>
                <CardContent>
                    <Button variant="secondary" className="w-full text-primary font-semibold hover:bg-white/90">
                        查看使用指南
                    </Button>
                </CardContent>
                <div className="absolute top-0 right-0 -mt-4 -mr-4 h-24 w-24 rounded-full bg-white/10 blur-2xl" />
            </Card>
        </motion.div>
      </div>
    </motion.div>
  );
}
