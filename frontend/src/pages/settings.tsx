import { useState } from "react";
import { useNavigate } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { LucideIcon } from "lucide-react";
import {
  Check,
  Cpu,
  Database,
  HardDrive,
  LogIn,
  LogOut,
  Monitor,
  Moon,
  RefreshCw,
  Sun,
  User as UserIcon,
  X,
} from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { systemApi } from "@/shared/api/system";
import type { HealthStatus } from "@/shared/api/types";
import { formatBytes } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useAuthStore } from "@/stores/auth";
import { useUiStore, type Theme } from "@/stores/ui";
import { SubjectSelect } from "@/components/question/subject-select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";

// ---------------- 通用小部件 ----------------

function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback;
  return fallback;
}

function QueryError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>加载失败</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center justify-between gap-2">
        <span>{errorText(error, "网络异常，请稍后重试")}</span>
        <Button size="sm" variant="outline" onClick={onRetry}>
          重试
        </Button>
      </AlertDescription>
    </Alert>
  );
}

function CardRowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-9 w-full" />
      ))}
    </div>
  );
}

// ---------------- 外观 ----------------

const THEME_OPTIONS: { value: Theme; label: string; desc: string; icon: LucideIcon }[] = [
  { value: "light", label: "浅色", desc: "米白纸感", icon: Sun },
  { value: "dark", label: "深色", desc: "墨蓝灰", icon: Moon },
  { value: "system", label: "跟随系统", desc: "随系统自动切换", icon: Monitor },
];

function AppearanceCard() {
  const theme = useUiStore((s) => s.theme);
  const setTheme = useUiStore((s) => s.setTheme);
  const sidebarCollapsed = useUiStore((s) => s.sidebarCollapsed);
  const toggleSidebar = useUiStore((s) => s.toggleSidebar);

  return (
    <Card>
      <CardHeader>
        <CardTitle>外观</CardTitle>
        <CardDescription>主题与界面布局偏好，即时生效并保存在本地</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="space-y-2.5">
          <Label>主题</Label>
          <RadioGroup
            value={theme}
            onValueChange={(v) => setTheme(v as Theme)}
            className="grid grid-cols-1 sm:grid-cols-3"
          >
            {THEME_OPTIONS.map((opt) => {
              const Icon = opt.icon;
              const active = theme === opt.value;
              return (
                <label
                  key={opt.value}
                  className={cn(
                    "flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3 transition-colors hover:bg-accent/50",
                    active && "border-primary/50 bg-accent/60 ring-1 ring-primary/30",
                  )}
                >
                  <RadioGroupItem value={opt.value} aria-label={opt.label} />
                  <Icon className="size-4 shrink-0 text-muted-foreground" />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium">{opt.label}</span>
                    <span className="block text-xs text-muted-foreground">{opt.desc}</span>
                  </span>
                </label>
              );
            })}
          </RadioGroup>
        </div>
        <Separator />
        <div className="flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <Label htmlFor="sidebar-collapsed">侧栏默认折叠</Label>
            <p className="text-xs text-muted-foreground">折叠后侧栏仅保留图标，为主内容留出更多空间</p>
          </div>
          <Switch
            id="sidebar-collapsed"
            checked={sidebarCollapsed}
            onCheckedChange={(checked) => {
              if (checked !== sidebarCollapsed) toggleSidebar();
            }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------- 账号 ----------------

function roleLabel(role?: string): string {
  if (role === "admin") return "管理员";
  if (role === "user") return "普通用户";
  return role || "用户";
}

function AccountCard() {
  const navigate = useNavigate();
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const toast = useUiStore((s) => s.toast);
  const [pending, setPending] = useState(false);

  const onLogout = async () => {
    setPending(true);
    try {
      await logout();
      toast({ title: "已退出登录", variant: "success" });
      navigate("/login");
    } finally {
      setPending(false);
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>账号</CardTitle>
        <CardDescription>当前登录身份与会话管理</CardDescription>
      </CardHeader>
      <CardContent>
        {user ? (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                <UserIcon className="size-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{user.username}</span>
                  <Badge variant={user.role === "admin" ? "default" : "secondary"}>
                    {roleLabel(user.role)}
                  </Badge>
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">用户 ID：{user.user_id}</div>
              </div>
            </div>
            <Button variant="outline" onClick={onLogout} disabled={pending}>
              {pending ? <Spinner /> : <LogOut />}
              退出登录
            </Button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="text-sm font-medium">当前为本地用户模式</div>
              <p className="mt-0.5 text-xs text-muted-foreground">
                未登录可使用基础功能；登录管理员账号后可管理模型设置等高级能力
              </p>
            </div>
            <Button onClick={() => navigate("/login")}>
              <LogIn />
              去登录
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------- 使用偏好 ----------------

function prefValueText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function UserPrefsCard() {
  const toast = useUiStore((s) => s.toast);
  const queryClient = useQueryClient();
  const [editedSubject, setEditedSubject] = useState<string | null>(null);

  const prefsQuery = useQuery({
    queryKey: ["user-settings"],
    queryFn: () => systemApi.userSettings(),
  });

  const saveMutation = useMutation({
    mutationFn: (settings: Record<string, any>) => systemApi.putUserSettings(settings),
    onSuccess: async () => {
      setEditedSubject(null);
      toast({ title: "使用偏好已保存", variant: "success" });
      await queryClient.invalidateQueries({ queryKey: ["user-settings"] });
    },
    onError: (err) => {
      toast({
        title: "保存失败",
        description: errorText(err, "网络异常，请稍后重试"),
        variant: "destructive",
      });
    },
  });

  const settings = prefsQuery.data?.settings ?? {};
  const serverSubject = typeof settings.default_subject === "string" ? settings.default_subject : "";
  const subject = editedSubject ?? serverSubject;
  const otherEntries = Object.entries(settings).filter(([k]) => k !== "default_subject");

  return (
    <Card>
      <CardHeader>
        <CardTitle>使用偏好</CardTitle>
        <CardDescription>默认学科等个人化选项，随账号保存</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {prefsQuery.isPending ? (
          <CardRowsSkeleton rows={3} />
        ) : prefsQuery.isError ? (
          <QueryError error={prefsQuery.error} onRetry={() => void prefsQuery.refetch()} />
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-3">
              <div className="w-full max-w-xs space-y-1.5">
                <Label>默认学科</Label>
                <SubjectSelect
                  value={subject || undefined}
                  onValueChange={(v) => setEditedSubject(v)}
                  placeholder="选择默认学科"
                />
              </div>
              <Button
                onClick={() => saveMutation.mutate({ ...settings, default_subject: subject })}
                disabled={saveMutation.isPending || !subject}
              >
                {saveMutation.isPending ? <Spinner className="text-primary-foreground" /> : null}
                保存偏好
              </Button>
            </div>
            {otherEntries.length > 0 ? (
              <>
                <Separator />
                <div className="space-y-1">
                  <div className="text-xs font-medium text-muted-foreground">其他已保存选项（只读）</div>
                  <div className="divide-y divide-border rounded-lg border border-border">
                    {otherEntries.map(([key, value]) => (
                      <div key={key} className="flex items-start justify-between gap-4 px-3 py-2">
                        <span className="shrink-0 font-mono text-xs text-muted-foreground">{key}</span>
                        <span className="min-w-0 break-all text-right text-xs">{prefValueText(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------- 模型设置（管理员） ----------------

interface ModelsDialogState {
  provider: string;
  count: number;
  models: string[];
}

function ModelSettingsCard() {
  const toast = useUiStore((s) => s.toast);
  const queryClient = useQueryClient();
  const [modelsDialog, setModelsDialog] = useState<ModelsDialogState | null>(null);

  const settingsQuery = useQuery({
    queryKey: ["model-settings"],
    queryFn: () => systemApi.modelSettings(),
    retry: false,
  });

  const activateMutation = useMutation({
    mutationFn: (name: string) => systemApi.putModelSettings({ active_provider: name }),
    onSuccess: async (_data, name) => {
      toast({ title: "已切换激活 Provider", description: name, variant: "success" });
      await queryClient.invalidateQueries({ queryKey: ["model-settings"] });
    },
    onError: (err) => {
      toast({
        title: "切换失败",
        description: errorText(err, "网络异常，请稍后重试"),
        variant: "destructive",
      });
    },
  });

  const fetchModelsMutation = useMutation({
    mutationFn: (provider: string) => systemApi.fetchModels({ provider }),
    onSuccess: (data, provider) => {
      setModelsDialog({
        provider,
        count: data.count ?? (data.models ?? []).length,
        models: (data.models ?? []).map((m) => m.id),
      });
    },
    onError: (err, provider) => {
      toast({
        title: `拉取 ${provider} 模型失败`,
        description: errorText(err, "网络异常，请稍后重试"),
        variant: "destructive",
      });
    },
  });

  const data = settingsQuery.data;
  const providers = data?.providers ?? [];
  const forbidden =
    settingsQuery.isError && settingsQuery.error instanceof ApiError && settingsQuery.error.status === 403;

  return (
    <Card>
      <CardHeader>
        <CardTitle>模型设置</CardTitle>
        <CardDescription>查看并切换 LLM Provider，密钥仅以脱敏状态展示</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {settingsQuery.isPending ? (
          <CardRowsSkeleton rows={4} />
        ) : forbidden ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
            当前账号无权查看模型设置，请使用管理员账号登录。
          </p>
        ) : settingsQuery.isError ? (
          <QueryError error={settingsQuery.error} onRetry={() => void settingsQuery.refetch()} />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-muted-foreground">当前激活 Provider：</span>
              <span className="font-medium">{data?.active_provider || "—"}</span>
              {data?.pinned ? <Badge variant="secondary">已固定</Badge> : null}
            </div>
            {providers.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
                尚未配置任何模型 Provider
              </p>
            ) : (
              <div className="divide-y divide-border rounded-lg border border-border">
                {providers.map((p) => {
                  const isActive = p.name === data?.active_provider;
                  const activating = activateMutation.isPending && activateMutation.variables === p.name;
                  const fetching = fetchModelsMutation.isPending && fetchModelsMutation.variables === p.name;
                  return (
                    <div key={p.name} className="flex flex-wrap items-center gap-2 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium">{p.name}</span>
                          {isActive ? <Badge variant="default">当前激活</Badge> : null}
                          {p.api_key_set ? (
                            <Badge variant="success">已配置 Key</Badge>
                          ) : (
                            <Badge variant="muted">未配置</Badge>
                          )}
                        </div>
                        {p.base_url ? (
                          <div className="mt-0.5 truncate text-xs text-muted-foreground">{p.base_url}</div>
                        ) : null}
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={isActive || activateMutation.isPending}
                        onClick={() => activateMutation.mutate(p.name)}
                      >
                        {activating ? <Spinner /> : null}
                        设为激活
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={fetchModelsMutation.isPending}
                        onClick={() => fetchModelsMutation.mutate(p.name)}
                      >
                        {fetching ? <Spinner /> : <RefreshCw />}
                        拉取模型
                      </Button>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}
      </CardContent>

      <Dialog open={modelsDialog !== null} onOpenChange={(open) => !open && setModelsDialog(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{modelsDialog ? `${modelsDialog.provider} 可用模型` : "可用模型"}</DialogTitle>
            <DialogDescription>共 {modelsDialog?.count ?? 0} 个模型</DialogDescription>
          </DialogHeader>
          <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
            {modelsDialog && modelsDialog.models.length > 0 ? (
              <ul className="divide-y divide-border">
                {modelsDialog.models.map((id) => (
                  <li key={id} className="px-3 py-2 font-mono text-xs">
                    {id}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-3 py-8 text-center text-sm text-muted-foreground">该 Provider 未返回任何模型</p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

// ---------------- 系统状态 ----------------

const CONFIG_FLAGS: { key: string; label: string }[] = [
  { key: "chat_configured", label: "对话模型" },
  { key: "lesson_plan_configured", label: "教案模型" },
  { key: "openrouter_configured", label: "OpenRouter" },
  { key: "moonshot_configured", label: "Moonshot" },
  { key: "fireworks_configured", label: "Fireworks" },
  { key: "zhipu_configured", label: "智谱" },
  { key: "metaso_configured", label: "秘塔搜索" },
  { key: "tavily_configured", label: "Tavily" },
];

function healthStatusBadge(status?: string) {
  if (status === "healthy") return <Badge variant="success">健康</Badge>;
  if (status === "degraded") return <Badge variant="warning">降级运行</Badge>;
  if (status === "unhealthy") return <Badge variant="destructive">异常</Badge>;
  return <Badge variant="muted">{status || "未知"}</Badge>;
}

function CheckRow({
  icon: Icon,
  label,
  state,
  detail,
}: {
  icon: LucideIcon;
  label: string;
  state: "ok" | "warn" | "fail";
  detail?: string;
}) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span
        className={cn(
          "size-2 shrink-0 rounded-full",
          state === "ok" && "bg-success",
          state === "warn" && "bg-warning",
          state === "fail" && "bg-destructive",
        )}
      />
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="text-sm">{label}</span>
      <span className="ml-auto text-right text-xs text-muted-foreground">
        {detail ?? (state === "ok" ? "正常" : state === "warn" ? "部分可用" : "异常")}
      </span>
    </div>
  );
}

function SystemStatusCard() {
  const healthQuery = useQuery({
    queryKey: ["system-health"],
    queryFn: async (): Promise<HealthStatus> => {
      try {
        return await systemApi.health();
      } catch (err) {
        // 后端在不健康时以 503 返回，但 detail 中仍携带完整健康载荷
        if (err instanceof ApiError && err.status === 503 && err.details && typeof err.details === "object") {
          return err.details as HealthStatus;
        }
        throw err;
      }
    },
  });

  const configQuery = useQuery({
    queryKey: ["system-config"],
    queryFn: () => systemApi.config(),
  });

  const health = healthQuery.data;
  const config = configQuery.data;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>系统状态</CardTitle>
          {health ? healthStatusBadge(health.status) : null}
        </div>
        <CardDescription>后端服务健康检查与各项能力配置概览</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {healthQuery.isPending ? (
          <CardRowsSkeleton rows={3} />
        ) : healthQuery.isError ? (
          <QueryError error={healthQuery.error} onRetry={() => void healthQuery.refetch()} />
        ) : (
          <div className="divide-y divide-border rounded-lg border border-border px-4">
            <CheckRow
              icon={Database}
              label="数据库"
              state={health?.checks?.db?.ok ? "ok" : "fail"}
              detail={health?.checks?.db?.ok ? "连接正常" : health?.checks?.db?.error || "连接失败"}
            />
            <CheckRow
              icon={HardDrive}
              label="磁盘空间"
              state={health?.checks?.disk?.ok ? "ok" : "fail"}
              detail={
                health?.checks?.disk?.ok
                  ? `剩余 ${formatBytes(health?.checks?.disk?.free_bytes)} / 共 ${formatBytes(
                      health?.checks?.disk?.total_bytes,
                    )}`
                  : health?.checks?.disk?.error || "可用空间不足"
              }
            />
            <CheckRow
              icon={Cpu}
              label="模型服务"
              state={
                health?.checks?.llm?.ok === false
                  ? "fail"
                  : health?.checks?.llm?.configured
                    ? "ok"
                    : "warn"
              }
              detail={health?.checks?.llm?.configured ? "已配置模型服务" : "未配置模型 Key，AI 功能受限"}
            />
          </div>
        )}

        <Separator />

        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">能力配置</div>
          {configQuery.isPending ? (
            <div className="flex flex-wrap gap-2">
              {CONFIG_FLAGS.map((f) => (
                <Skeleton key={f.key} className="h-6 w-24" />
              ))}
            </div>
          ) : configQuery.isError ? (
            <QueryError error={configQuery.error} onRetry={() => void configQuery.refetch()} />
          ) : (
            <div className="flex flex-wrap gap-2">
              {CONFIG_FLAGS.map((f) => {
                const configured = config?.[f.key] === true;
                return (
                  <Badge
                    key={f.key}
                    variant={configured ? "success" : "muted"}
                    className="gap-1.5 px-2.5 py-1"
                  >
                    {configured ? <Check /> : <X />}
                    {f.label}
                    <span className="font-normal">{configured ? "已配置" : "未配置"}</span>
                  </Badge>
                );
              })}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------- 页面 ----------------

const SECTION_NAV = [
  { id: "appearance", label: "外观" },
  { id: "account", label: "账号" },
  { id: "prefs", label: "使用偏好" },
  { id: "model", label: "模型设置", adminOnly: true },
  { id: "system", label: "系统状态" },
] as const;

export function SettingsPage() {
  const user = useAuthStore((s) => s.user);
  // 后端 require_admin 显式排除本地用户（auth_source==="local"/user_id==="local-user"），
  // 本地模式下 role 虽为 admin，模型设置的写操作必 403——按“真实登录的管理员”门控
  const isAdmin = user?.role === "admin" && user.user_id !== "local-user";

  const sections = SECTION_NAV.filter((s) => !("adminOnly" in s && s.adminOnly) || isAdmin);

  return (
    <div className="mx-auto flex w-full max-w-[920px] items-start gap-8 animate-fade-in">
      {/* 稳定的设置分组导航（Quiet Form，§5.3） */}
      <nav aria-label="设置分组" className="sticky top-24 hidden w-36 shrink-0 md:block">
        <ul className="space-y-0.5">
          {sections.map((s) => (
            <li key={s.id}>
              <a
                href={`#settings-${s.id}`}
                className="block rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
              >
                {s.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {/* 单列表单，最大宽度约 720px */}
      <div className="w-full min-w-0 max-w-[720px] space-y-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">设置</h1>
          <p className="mt-1 text-sm text-muted-foreground">外观、账号、使用偏好与系统状态集中管理</p>
        </div>
        <section id="settings-appearance" className="scroll-mt-24">
          <AppearanceCard />
        </section>
        <section id="settings-account" className="scroll-mt-24">
          <AccountCard />
        </section>
        <section id="settings-prefs" className="scroll-mt-24">
          <UserPrefsCard />
        </section>
        {isAdmin ? (
          <section id="settings-model" className="scroll-mt-24">
            <ModelSettingsCard />
          </section>
        ) : null}
        <section id="settings-system" className="scroll-mt-24">
          <SystemStatusCard />
        </section>
      </div>
    </div>
  );
}
