import { useState } from "react";
import { CheckCircle2, ChevronRight, CircleAlert, LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { ToolStep } from "@/features/chat/ui/tool-step";
import type { ToolStepView } from "@/features/chat/model/types";
import type { KnowledgePointBoardItem, KnowledgePointBoardView } from "../model/selectors";
import { studyFailedCheckLabel, studySourceClassLabel } from "../model/tool-adapters";

function StatusBadge({ status }: { status: "running" | "done" | "error" }) {
  if (status === "running") {
    return (
      <Badge variant="outline" className="gap-1 text-tool-running">
        <LoaderCircle className="size-3 animate-spin" /> 检索中
      </Badge>
    );
  }
  if (status === "error") {
    return (
      <Badge variant="warning" className="gap-1">
        <CircleAlert className="size-3" /> 未通过
      </Badge>
    );
  }
  return (
    <Badge variant="success" className="gap-1">
      <CheckCircle2 className="size-3" /> 已完成
    </Badge>
  );
}

/**
 * 单行知识点：有嵌套工具时间线（并行子代理）时可展开，
 * 复用 chat 的 ToolStep 视觉；legacy 行（无 steps）渲染为不可展开的扁平行。
 */
function KpRow({
  item,
  onInspect,
}: {
  item: KnowledgePointBoardItem;
  onInspect?: (tool: ToolStepView) => void;
}) {
  const expandable = Boolean(item.steps?.length);
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-lg border border-border bg-surface/50 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        {expandable ? (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={open ? `收起 ${item.title} 的子代理工具时间线` : `展开 ${item.title} 的子代理工具时间线`}
            className="flex shrink-0 items-center text-muted-foreground transition-colors hover:text-foreground"
          >
            <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
          </button>
        ) : (
          <span aria-hidden className="size-3.5 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate font-medium">{item.title}</span>
        <StatusBadge status={item.status} />
        {item.index !== undefined && item.total !== undefined ? (
          <span className="text-xs tabular-nums text-muted-foreground">
            {item.index}/{item.total}
          </span>
        ) : null}
        {item.sourceCount !== undefined ? (
          <span className="text-xs text-muted-foreground">{item.sourceCount} 个来源</span>
        ) : null}
        {item.sourceClasses.map((cls) => (
          <Badge key={cls} variant="muted">
            {studySourceClassLabel(cls)}
          </Badge>
        ))}
        {item.failedChecks.length > 0 ? (
          <span className="flex basis-full flex-wrap gap-1">
            {item.failedChecks.map((check) => (
              <Badge key={check} variant="warning">
                {studyFailedCheckLabel(check)}
              </Badge>
            ))}
          </span>
        ) : null}
      </div>
      {open && item.steps && item.steps.length > 0 ? (
        <div className="mt-2 space-y-1.5 pl-[18px]">
          {item.steps.map((step) => (
            <ToolStep key={step.id} tool={step} {...(onInspect ? { onInspect } : {})} />
          ))}
        </div>
      ) : null}
    </li>
  );
}

/** 知识点看板：检索/审查进度逐点可见，失败检查给出中文说明，并行子代理可展开工具时间线。 */
export function KnowledgePointBoard({
  board,
  onInspect,
}: {
  board: KnowledgePointBoardView;
  onInspect?: (tool: ToolStepView) => void;
}) {
  if (board.items.length === 0) return null;
  return (
    <section
      aria-label="知识点进度"
      className="rounded-xl border border-border bg-card px-4 py-3 shadow-soft"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold text-muted-foreground">知识点进度</h3>
        {board.serverReported ? (
          <span className="text-[11px] text-muted-foreground">服务端快照 · 重连后回填</span>
        ) : null}
      </div>
      <ul className="mt-2 space-y-2">
        {board.items.map((item) => (
          <KpRow key={item.key} item={item} onInspect={onInspect} />
        ))}
      </ul>
      {board.failedChecks.length > 0 ? (
        <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
          未通过检查：{board.failedChecks.map(studyFailedCheckLabel).join("；")}
        </p>
      ) : null}
    </section>
  );
}
