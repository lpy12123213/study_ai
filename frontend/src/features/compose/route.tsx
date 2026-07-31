import { useState } from "react";
import { useLocation, useSearchParams } from "react-router";
import { ClipboardCheck, Layers, Search } from "lucide-react";
import { parseEnumParam, parseStringParam, updateSearchParams } from "@/shared/lib/search-params";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SearchTab } from "./components/search-tab";
import { BlueprintTab } from "./components/blueprint-tab";
import { ReviewTab } from "./components/review-tab";


// ---------------- 页面 ----------------

export function ComposeRoute() {
  // tab 与审核任务 ID 入 URL（架构 §8.4）：/compose?tab=review&review=<taskId> 可直达
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseEnumParam(searchParams, "tab", ["search", "blueprint", "review"] as const) ?? "search";
  const reviewFocus = parseStringParam(searchParams, "review") ?? null;
  const setTab = (v: string) =>
    setSearchParams((prev) => updateSearchParams(prev, { tab: v === "search" ? null : v }), { replace: true });
  const gotoReview = (taskId: string) =>
    setSearchParams((prev) => updateSearchParams(prev, { tab: "review", review: taskId }));
  // 首页 Intent Workspace 带入的关键词预填（useState 初始化即消费，无需 effect）
  const location = useLocation();
  const [prefillKeyword] = useState(
    () => (location.state as { prefillKeyword?: string } | null)?.prefillKeyword ?? "",
  );

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 animate-fade-in">
      <header>
        <h1 className="text-xl font-semibold tracking-tight">组卷工作室</h1>
        <p className="mt-1 text-sm text-muted-foreground">搜题鉴别、蓝图组卷与人工审核的一体化工作台</p>
      </header>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="search">
            <Search /> 搜题
          </TabsTrigger>
          <TabsTrigger value="blueprint">
            <Layers /> 蓝图组卷
          </TabsTrigger>
          <TabsTrigger value="review">
            <ClipboardCheck /> 人工审核
          </TabsTrigger>
        </TabsList>

        <TabsContent value="search" forceMount>
          <SearchTab initialKeyword={prefillKeyword} />
        </TabsContent>
        <TabsContent value="blueprint" forceMount>
          <BlueprintTab onGotoReview={gotoReview} />
        </TabsContent>
        <TabsContent value="review" forceMount>
          <ReviewTab focusTaskId={reviewFocus} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
