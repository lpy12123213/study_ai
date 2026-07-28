import type { ReactNode } from "react";
import { SendHorizontal, Square } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface PromptComposerProps {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  /** 生成中：右侧按钮切换为「停止接收」（不声称服务端已取消，§9.2）。 */
  sending?: boolean;
  onStop?: () => void;
  /** 底部左侧槽位：学科选择、模式切换等（§10）。 */
  leftSlot?: ReactNode;
  placeholder?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  /** 提交按钮文案（默认「发送」，首页 Intent Workspace 用「开始」）。 */
  submitLabel?: string;
  /**
   * 停止按钮文案（默认「停止接收」）。仅当调用方具备服务端取消契约时
   * 才应传入「停止任务」（§9.2：无契约的流不得声称服务端已停止）。
   */
  stopLabel?: string;
  /** 停止按钮悬浮说明（与 stopLabel 配套）。 */
  stopTitle?: string;
  className?: string;
}

/**
 * 输入舱（规划 §10）：24px 圆角，文本区与工具栏同一表面，最小高度约 112px。
 * Enter 发送、Shift+Enter 换行；停止语义为「停止接收」。
 * 无状态组件：不导入 API 或 store，可复用于对话页与首页 Intent Workspace。
 */
export function PromptComposer({
  value,
  onChange,
  onSubmit,
  sending = false,
  onStop,
  leftSlot,
  placeholder = "输入你的问题，Enter 发送，Shift+Enter 换行",
  autoFocus,
  disabled,
  submitLabel = "发送",
  stopLabel = "停止接收",
  stopTitle = "停止接收当前生成",
  className,
}: PromptComposerProps) {
  return (
    <form
      className={cn(
        "min-h-[112px] rounded-2xl border border-border bg-composer-surface p-2.5 shadow-soft focus-within:border-spectral/50",
        className,
      )}
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <Textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            onSubmit();
          }
        }}
        placeholder={placeholder}
        disabled={disabled ?? sending}
        className="max-h-40 min-h-[72px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
        autoFocus={autoFocus}
      />
      <div className="mt-1 flex items-center justify-between gap-2 px-1 pb-0.5">
        <div className="flex min-w-0 items-center gap-1">{leftSlot}</div>
        {sending ? (
          <Button type="button" variant="destructive" onClick={onStop} title={stopTitle}>
            <Square />
            {stopLabel}
          </Button>
        ) : (
          <Button type="submit" disabled={!value.trim()}>
            <SendHorizontal />
            {submitLabel}
          </Button>
        )}
      </div>
    </form>
  );
}
