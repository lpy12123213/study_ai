import { Check, Circle, LoaderCircle, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { StudyMaterialsStageView } from "../model/types";

function StageIcon({ stage }: { stage: StudyMaterialsStageView }) {
  if (stage.status === "success") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-tool-success/15 text-tool-success">
        <Check className="size-3" />
      </span>
    );
  }
  if (stage.status === "error") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-tool-error/15 text-tool-error">
        <X className="size-3" />
      </span>
    );
  }
  if (stage.status === "running") {
    return (
      <span className="flex size-5 items-center justify-center rounded-full bg-tool-running/15 text-tool-running">
        <LoaderCircle className="size-3 animate-spin" />
      </span>
    );
  }
  return (
    <span className="flex size-5 items-center justify-center rounded-full border border-timeline-rail text-tool-idle">
      <Circle className="size-2" />
    </span>
  );
}

export function StageProgress({ stages }: { stages: StudyMaterialsStageView[] }) {
  return (
    <div>
      <ol
        aria-label="资料生成阶段（由工具活动推断）"
        className="flex min-w-max items-center rounded-xl border border-border bg-surface px-3 py-2 shadow-soft"
      >
        {stages.map((stage, index) => (
          <li key={stage.id} className="flex items-center">
            {index > 0 ? (
              <span
                aria-hidden
                className={cn(
                  "mx-1.5 h-px w-5 sm:w-7",
                  stage.status === "success" || stage.status === "running" ? "bg-spectral/50" : "bg-timeline-rail",
                )}
              />
            ) : null}
            <div
              className={cn(
                "flex items-center gap-1.5 text-xs font-medium",
                stage.status === "running" && "text-tool-running",
                stage.status === "success" && "text-tool-success",
                stage.status === "error" && "text-tool-error",
                stage.status === "pending" && "text-muted-foreground",
              )}
            >
              <StageIcon stage={stage} />
              <span>{stage.label}</span>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-1.5 text-[11px] text-muted-foreground">
        阶段由当前工具活动推断；legacy 任务不提供权威 workflow_stage。
      </p>
    </div>
  );
}
