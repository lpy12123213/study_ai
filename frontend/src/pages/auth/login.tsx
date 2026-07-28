import { useState } from "react";
import { useNavigate } from "react-router";
import { GraduationCap } from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { useAuthStore } from "@/stores/auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";

export function LoginPage() {
  const navigate = useNavigate();
  const login = useAuthStore((s) => s.login);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("请输入用户名和密码");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.code === "invalid_credentials") setError("用户名或密码错误");
        else if (err.code === "login_locked") setError("失败次数过多，账号已临时锁定，请 5 分钟后再试");
        else setError(err.message || "登录失败，请重试");
      } else {
        setError("网络异常，请确认后端服务已启动");
      }
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-sm animate-slide-up">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lift">
            <GraduationCap className="size-6" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold tracking-tight">Study AI</h1>
            <p className="mt-1 text-sm text-muted-foreground">本地优先的学习与出题工作台</p>
          </div>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>登录</CardTitle>
            <CardDescription>使用管理员账号登录以解锁全部管理能力</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-4">
              {error ? (
                <Alert variant="destructive">
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              ) : null}
              <div className="space-y-1.5">
                <Label htmlFor="username">用户名</Label>
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  placeholder="admin"
                  autoFocus
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">密码</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="••••••••"
                />
              </div>
              <Button type="submit" className="w-full" disabled={pending}>
                {pending ? <Spinner className="text-primary-foreground" /> : null}
                登录
              </Button>
              <Button type="button" variant="ghost" className="w-full text-muted-foreground" onClick={() => navigate("/")}>
                暂不登录，以本地用户身份进入
              </Button>
            </form>
          </CardContent>
        </Card>
        <p className="mt-6 text-center text-xs text-muted-foreground">
          本地部署模式下未登录也可使用基础功能；管理功能需要管理员账号。
        </p>
      </div>
    </div>
  );
}
