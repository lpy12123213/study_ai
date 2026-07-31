import { useNavigate } from "react-router";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";


/** 生成试卷 / 组卷结果的统一结果卡。 */
export function ComposeResultCard({ result }: { result: any }) {
  const navigate = useNavigate();
  const pid = result?.paperId ?? result?.id;
  const name = String(result?.paperName ?? result?.name ?? "未命名试卷");
  const count =
    result?.questionCount ?? (Array.isArray(result?.questions) ? (result.questions as unknown[]).length : undefined);
  return (
    <Card className="border-success/40 bg-success/5">
      <CardContent className="flex items-center gap-3 p-4">
        <CheckCircle2 className="size-5 shrink-0 text-success" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">{name}</div>
          <div className="text-xs text-muted-foreground">
            试卷已生成{typeof count === "number" ? `，共 ${count} 题` : ""}
          </div>
        </div>
        {pid != null ? (
          <Button size="sm" onClick={() => navigate(`/papers/${pid}`)}>
            查看试卷
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

