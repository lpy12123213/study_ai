import { CheckCircle2, CircleAlert, Info, TriangleAlert, X } from "lucide-react";

import { cn } from "@/lib/utils";
import { useUiStore, type ToastItem } from "@/stores/ui";

const ICONS = {
  default: Info,
  success: CheckCircle2,
  destructive: CircleAlert,
  warning: TriangleAlert,
} as const;

const STYLES = {
  default: "border-border [&>svg]:text-muted-foreground",
  success: "border-success/40 [&>svg]:text-success",
  destructive: "border-destructive/40 [&>svg]:text-destructive",
  warning: "border-warning/50 [&>svg]:text-warning",
} as const;

function ToastCard({ toast }: { toast: ToastItem }) {
  const dismiss = useUiStore((s) => s.dismissToast);
  const variant = toast.variant ?? "default";
  const Icon = ICONS[variant];
  return (
    <div
      className={cn(
        "pointer-events-auto flex w-80 animate-slide-up items-start gap-2.5 rounded-lg border bg-popover p-3.5 text-popover-foreground shadow-lift",
        STYLES[variant],
      )}
      role="status"
    >
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium leading-snug">{toast.title}</div>
        {toast.description ? (
          <div className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{toast.description}</div>
        ) : null}
      </div>
      <button
        onClick={() => dismiss(toast.id)}
        className="shrink-0 cursor-pointer rounded-md p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        aria-label="关闭提示"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

export function Toaster() {
  const toasts = useUiStore((s) => s.toasts);
  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2">
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} />
      ))}
    </div>
  );
}
