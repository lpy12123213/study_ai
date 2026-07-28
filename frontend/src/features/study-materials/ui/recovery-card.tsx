import { AlertTriangle, RotateCcw, Search, Sparkles, Workflow } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { StudyMaterialsRecoveryView } from "../model/types";

const STAGE_LABELS: Record<string, string> = {
  plan: "规划",
  search: "检索与研究",
  research: "检索与研究",
  aggregate: "聚合大纲",
  draft: "写作",
  write: "写作",
  revise: "写作",
  review: "审查",
  accept: "审查",
  export: "导出",
};

/** recovery.code → 专属说明；检索服务故障与质量门未通过要区分开。 */
const CODE_COPY: Record<string, string> = {
  research_tool_outage: "检索服务暂时不可用，稍后可直接继续。",
};

export function RecoveryCard({
  message,
  recovery,
  onContinue,
  onRegenerate,
  disabled,
}: {
  message: string;
  recovery?: StudyMaterialsRecoveryView;
  onContinue: (mode: "resume_failed_stage" | "retry_search" | "replan_from_failure") => void;
  /** recoverable === false 时的「重新生成」入口（复用同一组参数）。 */
  onRegenerate?: () => void;
  disabled?: boolean;
}) {
  const stageLabel = recovery?.stage ? STAGE_LABELS[recovery.stage] ?? recovery.stage : "当前";
  const codeCopy = recovery?.code ? CODE_COPY[recovery.code] : undefined;
  return (
    <section className="rounded-2xl border border-tool-error/35 bg-tool-error/5 p-5 shadow-soft" aria-label="失败恢复">
      <div className="flex items-center gap-2">
        <span className="flex size-8 items-center justify-center rounded-full bg-tool-error/12 text-tool-error">
          <AlertTriangle className="size-4" />
        </span>
        <div>
          <h2 className="text-sm font-semibold text-tool-error">生成失败</h2>
          <p className="text-xs text-muted-foreground">{stageLabel}阶段</p>
        </div>
      </div>
      <p className="mt-3 text-sm leading-6 text-muted-foreground">
        {message}
        {codeCopy ? ` ${codeCopy}` : ""}
        {recovery?.recoverable !== false && !codeCopy ? " 已完成的步骤与检索结果会被保留，无需从头再来。" : ""}
      </p>
      {recovery?.issues.length ? (
        <ul className="mt-2 list-inside list-disc space-y-1 text-xs text-muted-foreground">
          {recovery.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      ) : null}
      {recovery?.recoverable !== false ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="destructive"
            disabled={disabled}
            onClick={() => onContinue("resume_failed_stage")}
          >
            <RotateCcw /> 从失败阶段继续
          </Button>
          <Button size="sm" variant="outline" disabled={disabled} onClick={() => onContinue("retry_search")}>
            <Search /> 重试检索
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled}
            onClick={() => onContinue("replan_from_failure")}
          >
            <Workflow /> 重新规划
          </Button>
        </div>
      ) : onRegenerate ? (
        <div className="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="destructive" disabled={disabled} onClick={onRegenerate}>
            <Sparkles /> 重新生成
          </Button>
        </div>
      ) : null}
    </section>
  );
}
