import { CheckCircle2, CircleAlert, LoaderCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { KnowledgePointBoardView } from "../model/selectors";
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

/** 知识点看板：检索/审查进度逐点可见，失败检查给出中文说明。 */
export function KnowledgePointBoard({ board }: { board: KnowledgePointBoardView }) {
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
          <li key={item.key} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <span className="min-w-0 flex-1 truncate font-medium">{item.title}</span>
            <StatusBadge status={item.status} />
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
          </li>
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
