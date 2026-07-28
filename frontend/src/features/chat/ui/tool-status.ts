import { CheckCircle2, Circle, LoaderCircle, Square, Unplug, XCircle } from "lucide-react";

import type { ToolStepStatus } from "../model/types";

/** 状态 → 图标 / 文案 / 颜色（三者同时表达，不只靠颜色）。 */
export const TOOL_STATUS_META: Record<ToolStepStatus, { label: string; className: string; Icon: typeof Circle }> = {
  queued: { label: "等待中", className: "text-tool-idle", Icon: Circle },
  running: { label: "执行中", className: "text-tool-running", Icon: LoaderCircle },
  success: { label: "已完成", className: "text-tool-success", Icon: CheckCircle2 },
  error: { label: "失败", className: "text-tool-error", Icon: XCircle },
  interrupted: { label: "已停止接收，状态未知", className: "text-tool-idle", Icon: Unplug },
  stopped: { label: "已停止", className: "text-tool-idle", Icon: Square },
};

export function toolStatusLabel(status: ToolStepStatus): string {
  return TOOL_STATUS_META[status].label;
}
