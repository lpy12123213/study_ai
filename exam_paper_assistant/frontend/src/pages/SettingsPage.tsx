import { API_BASE_URL } from "@/lib/apiUrl";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { useHealth, useRuntimeConfig } from "@/hooks/useSystem";
import { motion, type Variants } from "framer-motion";
import { Activity, Server, Settings2, Trash2 } from "lucide-react";

const LOCAL_KEYS = [
  "epa_theme",
  "epa_subject_name",
  "epa_show_tool_messages",
  "epa_model_override",
  "epa_sub_model_override",
  "epa_learn_subject_name",
  "epa_learn_model_override",
  "epa_learn_left_panel_collapsed",
  "epa_learn_right_panel_collapsed",
  "epa_blueprint_left_panel_collapsed",
  "epa_blueprint_right_panel_collapsed",
  "epa_paper_detail_left_panel_collapsed",
  "epa_paper_detail_right_panel_collapsed",
  "epa_flow_left_panel_collapsed",
  "epa_flow_right_panel_collapsed",
];

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

export default function SettingsPage() {
  const healthQuery = useHealth();
  const configQuery = useRuntimeConfig();

  const clearLocalSettings = () => {
    const ok = window.confirm("确定要清除本地设置吗？（仅清除浏览器 localStorage）");
    if (!ok) return;
    for (const k of LOCAL_KEYS) {
      try {
        window.localStorage.removeItem(k);
      } catch {
        // ignore
      }
    }
    window.location.reload();
  };

  return (
    <motion.div 
        className="h-full overflow-y-auto bg-muted/30 p-6 md:p-8"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
    >
      <motion.div variants={itemVariants} className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight">系统设置</h1>
        <p className="text-muted-foreground mt-2">
          查看运行状态与本地偏好设置
        </p>
      </motion.div>

      <div className="grid gap-6 md:grid-cols-2">
        <motion.div variants={itemVariants}>
            <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Activity className="h-5 w-5 text-primary" />
                    后端状态
                </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
                <div>
                    <span className="text-muted-foreground block mb-1">API Base URL</span>
                    <code className="bg-muted px-2 py-1 rounded text-xs font-mono">{API_BASE_URL}</code>
                </div>

                <div>
                    <span className="text-muted-foreground block mb-1">健康检查</span>
                    {healthQuery.isLoading ? (
                    <div className="flex items-center gap-2 text-muted-foreground">
                        <div className="h-2 w-2 rounded-full bg-muted-foreground animate-pulse" />
                        请求中…
                    </div>
                    ) : healthQuery.isError ? (
                    <div className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-destructive">
                        连接失败：{(healthQuery.error as Error).message}
                    </div>
                    ) : healthQuery.data ? (
                    <div className="flex items-center gap-2 rounded-md border bg-emerald-500/10 px-3 py-2 text-emerald-600 dark:text-emerald-400">
                        <div className="h-2 w-2 rounded-full bg-emerald-500" />
                        {healthQuery.data.status} · {healthQuery.data.service}
                    </div>
                    ) : (
                    <div className="text-muted-foreground">暂无数据</div>
                    )}
                </div>
            </CardContent>
            </Card>
        </motion.div>

        <motion.div variants={itemVariants}>
            <Card className="h-full flex flex-col">
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Server className="h-5 w-5 text-primary" />
                    运行配置
                </CardTitle>
                <CardDescription>当前后端运行的配置摘要</CardDescription>
            </CardHeader>
            <CardContent className="flex-1 min-h-[150px]">
                {configQuery.isLoading ? (
                <div className="text-sm text-muted-foreground">请求中…</div>
                ) : configQuery.isError ? (
                <div className="text-sm text-destructive">
                    获取失败：{(configQuery.error as Error).message}
                </div>
                ) : configQuery.data ? (
                <pre className="h-full w-full rounded-md bg-muted p-3 text-[10px] text-muted-foreground overflow-x-auto font-mono custom-scrollbar">
                    {JSON.stringify(configQuery.data, null, 2)}
                </pre>
                ) : (
                <div className="text-sm text-muted-foreground">暂无数据</div>
                )}
            </CardContent>
            </Card>
        </motion.div>

        <motion.div variants={itemVariants} className="md:col-span-2">
            <Card>
            <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                    <Settings2 className="h-5 w-5 text-primary" />
                    本地偏好
                </CardTitle>
                <CardDescription>
                    管理存储在本地浏览器中的设置 (LocalStorage)
                </CardDescription>
            </CardHeader>
            <CardContent>
                <div className="flex flex-col sm:flex-row items-center justify-between gap-4 rounded-lg border p-4 bg-muted/20">
                    <div className="text-sm text-muted-foreground">
                        <p>清除学科选择、模型参数等本地缓存。</p>
                        <p className="text-xs opacity-70 mt-1">如果遇到 UI 显示异常，可以尝试此操作。</p>
                    </div>
                    <Button variant="destructive" size="sm" onClick={clearLocalSettings} className="gap-2 whitespace-nowrap">
                        <Trash2 className="h-4 w-4" />
                        清除本地设置
                    </Button>
                </div>
            </CardContent>
            </Card>
        </motion.div>
      </div>
    </motion.div>
  );
}
