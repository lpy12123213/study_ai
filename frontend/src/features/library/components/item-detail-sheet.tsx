import { useQuery } from "@tanstack/react-query";
import { libraryApi } from "@/features/question-library/api";
import { StemHtml } from "@/components/question/stem-html";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { apiErrorText } from "../model/shared";


// ---------------- 题目详情（右侧 Sheet，Master-Detail §5.3） ----------------

export function ItemDetailSheet({ questionId, onClose }: { questionId: string; onClose: () => void }) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["library-item", questionId],
    queryFn: () => libraryApi.getItem(questionId),
  });

  const item = (data?.library_item ?? {}) as Record<string, unknown>;
  const cache = (data?.question_cache ?? {}) as Record<string, unknown>;
  const stem = String(cache.stem || item.stem || "");
  const answer = String(cache.answer || "");
  const analysis = String(cache.analysis || "");
  const entries = Object.entries(item).filter(
    ([k, v]) => k !== "stem" && v !== null && v !== undefined && v !== "",
  );

  return (
    <Sheet open onOpenChange={(o) => !o && onClose()}>
      <SheetContent side="right" className="flex w-full max-w-xl flex-col gap-0 p-0 sm:max-w-xl">
        <SheetHeader className="shrink-0 border-b border-border px-5 py-4">
          <SheetTitle>题目详情</SheetTitle>
          <SheetDescription className="font-mono text-xs">{questionId}</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-32 w-full" />
            </div>
          ) : isError ? (
            <Alert variant="destructive">
              <AlertDescription>{apiErrorText(error, "加载题目详情失败")}</AlertDescription>
            </Alert>
          ) : (
            <>
              {stem ? (
                <div>
                  <div className="mb-1 text-xs font-medium text-muted-foreground">题干</div>
                  <StemHtml html={stem} className="text-sm" />
                </div>
              ) : null}
              {answer ? (
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">答案</div>
                  <StemHtml html={answer} className="text-sm" />
                </div>
              ) : null}
              {analysis ? (
                <div className="rounded-lg bg-muted/50 p-3">
                  <div className="mb-1 text-xs font-medium text-muted-foreground">解析</div>
                  <StemHtml html={analysis} className="text-sm" />
                </div>
              ) : null}
              {entries.length > 0 ? (
                <div className="rounded-lg border border-border p-3">
                  <div className="mb-2 text-xs font-medium text-muted-foreground">题库条目字段</div>
                  <div>
                    {entries.map(([k, v]) => (
                      <div
                        key={k}
                        className="grid grid-cols-[8.5rem_1fr] gap-2 border-b border-border/60 py-1.5 text-xs last:border-0"
                      >
                        <span className="font-mono text-muted-foreground">{k}</span>
                        <span className="break-all">
                          {typeof v === "object" ? JSON.stringify(v) : String(v)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}

