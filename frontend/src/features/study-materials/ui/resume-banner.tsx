import { Clock3 } from "lucide-react";

import { Button } from "@/components/ui/button";

export function ResumeBanner({
  title,
  status,
  onResume,
  onDiscard,
  busy,
}: {
  title: string;
  /** 任务中心状态；completed 时切换为「重新接收输出并恢复视图」语义。 */
  status?: string;
  onResume: () => void;
  onDiscard: () => void;
  busy?: boolean;
}) {
  const completed = status === "completed";
  return (
    <div className="flex flex-col gap-3 rounded-xl border-2 border-spectral/60 bg-spectral/10 px-4 py-3.5 shadow-soft sm:flex-row sm:items-center">
      <span className="relative flex size-4 shrink-0 items-center justify-center">
        {completed ? (
          <Clock3 className="size-4 text-spectral" />
        ) : (
          <>
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-spectral/40" />
            <Clock3 className="relative size-4 text-spectral" />
          </>
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold text-foreground">
          {completed ? "检测到已完成的生成任务" : "生成仍在进行中"}
        </div>
        <div className="truncate text-xs text-muted-foreground">
          {completed
            ? `${title}，可重新接收输出并恢复视图。`
            : `${title}，可继续接收输出并恢复当前视图。`}
        </div>
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={onResume} disabled={busy}>
          {completed ? "恢复视图" : "继续接收生成"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onDiscard} disabled={busy}>
          放弃
        </Button>
      </div>
    </div>
  );
}
