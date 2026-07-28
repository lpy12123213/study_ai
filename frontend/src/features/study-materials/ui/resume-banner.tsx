import { Clock3 } from "lucide-react";

import { Button } from "@/components/ui/button";

export function ResumeBanner({
  title,
  onResume,
  onDiscard,
  busy,
}: {
  title: string;
  onResume: () => void;
  onDiscard: () => void;
  busy?: boolean;
}) {
  return (
    <div className="flex flex-col gap-3 rounded-xl border border-spectral/20 bg-surface-mist px-4 py-3 sm:flex-row sm:items-center">
      <Clock3 className="size-4 shrink-0 text-spectral" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">检测到未完成的生成任务</div>
        <div className="truncate text-xs text-muted-foreground">{title}，可继续接收输出并恢复当前视图。</div>
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={onResume} disabled={busy}>
          继续接收
        </Button>
        <Button size="sm" variant="ghost" onClick={onDiscard} disabled={busy}>
          放弃
        </Button>
      </div>
    </div>
  );
}
