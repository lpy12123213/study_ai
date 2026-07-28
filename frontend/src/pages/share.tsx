import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router";
import { Clock, GraduationCap, KeyRound, Link2Off, TriangleAlert } from "lucide-react";

import { ApiError } from "@/shared/api/http-client";
import { shareApi } from "@/features/sharing/api";
import type { PaperDetail, ShareMeta, StudyArchive } from "@/shared/api/types";
import { formatDateTime } from "@/lib/format";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { QuestionCard } from "@/components/question/question-card";
import { MarkdownView } from "@/components/markdown/markdown-view";

type SharedPaper = PaperDetail & { question_count?: number };

type SharedTemplate = {
  id?: number | string;
  name?: string;
  template_type?: string;
  description?: string;
  body?: Record<string, unknown> | null;
  created_at?: string;
  updated_at?: string;
  [k: string]: unknown;
};

type ShareContentData = {
  success?: boolean;
  item_type?: string;
  paper?: SharedPaper;
  study_archive?: StudyArchive;
  template?: SharedTemplate;
};

type ShareError = { kind: "not_found" | "expired" | "generic"; message?: string };

type Phase = "loading" | "password" | "loading-content" | "ready" | "error";

function mapShareError(err: unknown): ShareError {
  if (err instanceof ApiError) {
    if (err.status === 404) return { kind: "not_found" };
    if (err.status === 410 || err.code.includes("expired")) return { kind: "expired" };
    if (err.status === 429 || err.code === "rate_limited")
      return { kind: "generic", message: "尝试次数过多，请稍后再试" };
    return { kind: "generic", message: err.message };
  }
  return { kind: "generic", message: "网络异常，请确认后端服务已启动后重试" };
}

function isPasswordError(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.status === 401 || err.status === 403 || err.code.includes("password"))
  );
}

function BrandHeader() {
  return (
    <div className="mb-8 flex flex-col items-center gap-3">
      <div className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-lift">
        <GraduationCap className="size-6" />
      </div>
      <div className="text-center">
        <h1 className="text-xl font-semibold tracking-tight">Study AI</h1>
        <p className="mt-1 text-sm text-muted-foreground">本地优先的学习与出题工作台</p>
      </div>
    </div>
  );
}

function Footer({ meta }: { meta: ShareMeta | null }) {
  return (
    <div className="mt-10 space-y-1 text-center text-xs text-muted-foreground">
      <p>由 Study AI 生成分享</p>
      {meta?.expires_at ? <p>有效期至 {formatDateTime(meta.expires_at)}</p> : null}
    </div>
  );
}

function PaperView({ paper }: { paper: SharedPaper }) {
  const questions = Array.isArray(paper.questions) ? paper.questions : [];
  const count = paper.question_count ?? questions.length;
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">{paper.paper_name || "试卷"}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          <span>{formatDateTime(paper.created_at)}</span>
          <Badge variant="secondary">{count} 题</Badge>
        </div>
      </div>
      {questions.length === 0 ? (
        <EmptyState title="试卷暂无题目" description="该试卷还没有收录任何题目。" />
      ) : (
        <div className="space-y-3">
          {questions.map((q, i) => (
            <div key={q.question_id || i} className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">第 {q.order ?? i + 1} 题</div>
              <QuestionCard question={{ ...q, source_url: undefined }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StudyArchiveView({ archive }: { archive: StudyArchive }) {
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">{archive.topic || "学习资料"}</h2>
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
          {archive.subject ? <Badge variant="secondary">{archive.subject}</Badge> : null}
          {archive.preset ? <Badge variant="outline">{archive.preset}</Badge> : null}
          {archive.created_at ? <span>{formatDateTime(archive.created_at)}</span> : null}
        </div>
      </div>
      {archive.markdown ? (
        <Card className="p-5 sm:p-6">
          <MarkdownView content={archive.markdown} />
        </Card>
      ) : (
        <EmptyState title="暂无内容" description="该学习资料没有可展示的正文。" />
      )}
    </div>
  );
}

function TemplateView({ template }: { template: SharedTemplate }) {
  const body = template.body && typeof template.body === "object" ? template.body : {};
  const description =
    typeof template.description === "string"
      ? template.description
      : typeof body.description === "string"
        ? body.description
        : "";
  const rows: { label: string; value?: string }[] = [
    { label: "名称", value: template.name },
    { label: "类型", value: template.template_type },
    { label: "创建时间", value: template.created_at ? formatDateTime(template.created_at) : undefined },
    { label: "更新时间", value: template.updated_at ? formatDateTime(template.updated_at) : undefined },
  ];
  return (
    <div className="space-y-6 animate-fade-in">
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">{template.name || "模板"}</h2>
        <div className="flex flex-wrap items-center gap-2">
          {template.template_type ? <Badge variant="secondary">{template.template_type}</Badge> : null}
        </div>
        {description ? <p className="text-sm text-muted-foreground">{description}</p> : null}
      </div>
      <Card className="p-5">
        <dl className="space-y-3">
          {rows.map((row) => (
            <div key={row.label} className="flex items-baseline gap-4 text-sm">
              <dt className="w-20 shrink-0 text-muted-foreground">{row.label}</dt>
              <dd className="min-w-0 flex-1 break-all">{row.value || "—"}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <div className="space-y-2">
        <div className="text-sm font-medium text-muted-foreground">模板字段</div>
        <pre className="overflow-x-auto rounded-lg border border-border bg-muted p-4 text-xs leading-relaxed">
          {JSON.stringify(body, null, 2)}
        </pre>
      </div>
    </div>
  );
}

function ContentView({ content }: { content: ShareContentData }) {
  if (content.item_type === "paper" && content.paper) return <PaperView paper={content.paper} />;
  if (content.item_type === "study_archive" && content.study_archive)
    return <StudyArchiveView archive={content.study_archive} />;
  if (content.item_type === "template" && content.template)
    return <TemplateView template={content.template} />;
  return (
    <EmptyState
      icon={TriangleAlert}
      title="暂不支持的内容类型"
      description="该分享指向的内容类型无法在此页面展示。"
    />
  );
}

export function SharePage() {
  const { token } = useParams<{ token: string }>();
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<ShareError | null>(null);
  const [meta, setMeta] = useState<ShareMeta | null>(null);
  const [content, setContent] = useState<ShareContentData | null>(null);
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const requestedRef = useRef<string | null>(null);

  useEffect(() => {
    const tok = (token || "").trim();
    if (!tok) {
      setError({ kind: "not_found" });
      setPhase("error");
      return;
    }
    // 请求幂等（只读），用 ref 去重以避免 StrictMode 双 effect 重复拉取。
    if (requestedRef.current === tok) return;
    requestedRef.current = tok;

    setPhase("loading");
    setError(null);
    setMeta(null);
    setContent(null);
    setPassword("");
    setPasswordError(null);

    void (async () => {
      try {
        const m = await shareApi.meta(tok);
        setMeta(m);
        if (m.has_password) {
          setPhase("password");
          return;
        }
        setPhase("loading-content");
        const c = (await shareApi.content(tok)) as ShareContentData;
        setContent(c);
        setPhase("ready");
      } catch (err) {
        setError(mapShareError(err));
        setPhase("error");
      }
    })();
  }, [token]);

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    const tok = (token || "").trim();
    const pwd = password.trim();
    if (!tok) return;
    if (!pwd) {
      setPasswordError("请输入访问密码");
      return;
    }
    setPending(true);
    setPasswordError(null);
    try {
      await shareApi.validate(tok, pwd);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setError({ kind: "not_found" });
        setPhase("error");
      } else if (err instanceof ApiError && (err.status === 410 || err.code.includes("expired"))) {
        setError({ kind: "expired" });
        setPhase("error");
      } else if (isPasswordError(err)) {
        setPasswordError("密码不正确");
      } else if (err instanceof ApiError && (err.status === 429 || err.code === "rate_limited")) {
        setPasswordError("尝试次数过多，请稍后再试");
      } else if (err instanceof ApiError) {
        setPasswordError(err.message || "验证失败，请重试");
      } else {
        setPasswordError("网络异常，请稍后重试");
      }
      return;
    } finally {
      setPending(false);
    }

    setPhase("loading-content");
    try {
      const c = (await shareApi.content(tok, pwd)) as ShareContentData;
      setContent(c);
      setPhase("ready");
    } catch (err) {
      if (isPasswordError(err)) {
        setPasswordError("密码不正确");
        setPhase("password");
      } else {
        setError(mapShareError(err));
        setPhase("error");
      }
    }
  };

  if (phase === "loading" || phase === "loading-content") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background px-4">
        <Spinner className="size-6" />
        <p className="text-sm text-muted-foreground">{phase === "loading" ? "正在打开分享…" : "正在加载内容…"}</p>
      </div>
    );
  }

  if (phase === "error") {
    const kind = error?.kind ?? "generic";
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-md animate-slide-up">
          <BrandHeader />
          {kind === "not_found" ? (
            <EmptyState
              icon={Link2Off}
              title="分享链接不存在"
              description="链接可能已被删除或从未生成，请与分享者确认后重试。"
            />
          ) : kind === "expired" ? (
            <EmptyState
              icon={Clock}
              title="链接已过期"
              description="该分享已超过有效期，请向分享者重新获取链接。"
            />
          ) : (
            <EmptyState
              icon={TriangleAlert}
              title="加载失败"
              description={error?.message || "分享内容加载失败，请稍后重试。"}
            />
          )}
        </div>
      </div>
    );
  }

  if (phase === "password") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="w-full max-w-sm animate-slide-up">
          <BrandHeader />
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <KeyRound className="size-4 text-primary" />
                需要访问密码
              </CardTitle>
              <CardDescription>该分享已设置密码，请输入后查看内容</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={submitPassword} className="space-y-4">
                {passwordError ? (
                  <Alert variant="destructive">
                    <AlertDescription>{passwordError}</AlertDescription>
                  </Alert>
                ) : null}
                <div className="space-y-1.5">
                  <Label htmlFor="share-password">访问密码</Label>
                  <Input
                    id="share-password"
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="请输入密码"
                    autoFocus
                  />
                </div>
                <Button type="submit" className="w-full" disabled={pending}>
                  {pending ? <Spinner className="text-primary-foreground" /> : null}
                  查看分享内容
                </Button>
              </form>
            </CardContent>
          </Card>
          <Footer meta={meta} />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto w-full max-w-3xl px-4 py-10">
        <div className="mb-8 flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-soft">
            <GraduationCap className="size-4.5" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">Study AI</div>
            <div className="text-xs text-muted-foreground">分享内容</div>
          </div>
        </div>
        {content ? <ContentView content={content} /> : null}
        <Footer meta={meta} />
      </div>
    </div>
  );
}
