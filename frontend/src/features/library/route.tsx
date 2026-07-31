import { useState } from "react";
import { useSearchParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, LibraryBig } from "lucide-react";
import { libraryApi } from "@/features/question-library/api";
import type { LibraryPreview } from "@/shared/api/types";
import { parseEnumParam, updateSearchParams } from "@/shared/lib/search-params";
import { useUiStore } from "@/stores/ui";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { apiErrorText } from "./model/shared";
import { BrowsePanel } from "./components/browse-panel";
import { GeneratePanel } from "./components/generate-panel";
import { CrawlScorePanel } from "./components/crawl-score-panel";
import { PreviewReview } from "./components/preview-review";


// ---------------- 页面 ----------------

export function LibraryRoute() {
  const queryClient = useQueryClient();
  const toast = useUiStore((s) => s.toast);
  // tab 入 URL（架构 §8.4）：/library?tab=generate 可直达
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseEnumParam(searchParams, "tab", ["browse", "generate", "crawl"] as const) ?? "browse";
  const setTab = (v: string) =>
    setSearchParams((prev) => updateSearchParams(prev, { tab: v === "browse" ? null : v }), { replace: true });
  const [preview, setPreview] = useState<LibraryPreview | null>(null);
  const [resuming, setResuming] = useState(false);

  const pendingQuery = useQuery({
    queryKey: ["library-latest-pending-preview"],
    queryFn: () => libraryApi.latestPendingPreview(),
    staleTime: 15_000,
  });
  const pending = pendingQuery.data?.preview ?? null;

  const resumePending = async () => {
    if (!pending?.preview_id) return;
    setResuming(true);
    try {
      const pv = await libraryApi.preview(pending.preview_id);
      setPreview(pv);
    } catch (err) {
      toast({ title: "恢复预览失败", description: apiErrorText(err, "请稍后重试"), variant: "destructive" });
    } finally {
      setResuming(false);
    }
  };

  const exitPreview = (committed: boolean) => {
    setPreview(null);
    queryClient.invalidateQueries({ queryKey: ["library-latest-pending-preview"] });
    if (committed) queryClient.invalidateQueries({ queryKey: ["library-items"] });
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <header className="space-y-1">
        <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight">
          <LibraryBig className="size-5 text-primary" />
          题库
        </h1>
        <p className="text-sm text-muted-foreground">浏览本地题库、AI 出题审核入库、抓取与评分清洗</p>
      </header>

      {pending && !preview ? (
        <Alert variant="info">
          <History />
          <AlertTitle>有未完成的出题预览</AlertTitle>
          <AlertDescription className="flex flex-wrap items-center gap-3">
            <span>
              {[pending.subject, pending.topic].filter(Boolean).join(" · ") || "未命名"}（
              {pending.draft_count ?? pending.draft_questions?.length ?? 0} 题待审核）
            </span>
            <Button size="sm" variant="outline" onClick={resumePending} disabled={resuming}>
              {resuming ? <Spinner /> : null}
              恢复审核
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      {preview ? (
        <PreviewReview key={preview.preview_id} preview={preview} onExit={exitPreview} />
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="browse">题库浏览</TabsTrigger>
            <TabsTrigger value="generate">AI 出题</TabsTrigger>
            <TabsTrigger value="crawl">抓取与评分</TabsTrigger>
          </TabsList>
          <TabsContent value="browse">
            <BrowsePanel onGoGenerate={() => setTab("generate")} />
          </TabsContent>
          <TabsContent value="generate">
            <GeneratePanel onPreview={setPreview} />
          </TabsContent>
          <TabsContent value="crawl">
            <CrawlScorePanel />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
