import { AlertTriangle, Search } from "lucide-react";

import type { StudyMaterialsResearchRetryView } from "../model/types";

/**
 * 修订/检索补充条：审查未通过或检索重试期间的琥珀色提示。
 * 只在运行中有意义，done/error 由结果卡与恢复卡接管。
 */
export function RevisionStrip({
  issues,
  remainingAttempts,
  researchRetry,
}: {
  issues: string[];
  remainingAttempts?: number;
  researchRetry?: StudyMaterialsResearchRetryView;
}) {
  if (researchRetry) {
    const total = researchRetry.pointIds.length;
    return (
      <div
        role="status"
        className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm shadow-soft"
      >
        <div className="flex items-center gap-2">
          <Search className="size-4 shrink-0 text-warning" />
          <span className="font-medium">
            检索补充中
            {researchRetry.attempt !== undefined ? ` · 第 ${researchRetry.attempt} 次` : ""}
            {total > 0 ? `，共 ${total} 个知识点` : ""}
          </span>
        </div>
        {total > 0 ? (
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {researchRetry.pointIds.join("、")}
          </p>
        ) : null}
      </div>
    );
  }

  if (issues.length === 0) return null;
  return (
    <div
      role="status"
      className="rounded-xl border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm shadow-soft"
    >
      <div className="flex items-center gap-2">
        <AlertTriangle className="size-4 shrink-0 text-warning" />
        <span className="font-medium">
          质量审查未通过
          {remainingAttempts !== undefined ? ` · 剩余 ${remainingAttempts} 次修订机会` : "，正在修订"}
        </span>
      </div>
      <ul className="mt-1 list-inside list-disc space-y-0.5 text-xs leading-5 text-muted-foreground">
        {issues.map((issue) => (
          <li key={issue}>{issue}</li>
        ))}
      </ul>
    </div>
  );
}
