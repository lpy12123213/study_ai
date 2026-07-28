import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { useMediaQuery } from "@/lib/use-media-query";
import { useUiStore } from "@/stores/ui";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import type { ConversationTurnView } from "../model/types";
import { ToolInspector } from "./tool-inspector";

interface ToolInspectorHostProps {
  turn: ConversationTurnView;
  selectedToolId: string;
  onSelectTool: (id: string) => void;
  onClose: () => void;
}

/**
 * 工具检查器的响应式容器（视觉规划 §5.2 / §7.7）：
 * - 宽屏：附着式右侧面板（仅当主回答列保持 ≥640px 时附着，随全局侧栏状态动态计算断点）。
 * - 中屏：右侧覆盖 Sheet。
 * - 移动：底部 Sheet，默认 70dvh，可上拖至 90dvh / 下放回 70dvh。
 * 附着面板为页面布局的一部分（返回 aside 参与 flex 布局）；Sheet 模式 portal 覆盖。
 */
export function ToolInspectorHost({ turn, selectedToolId, onSelectTool, onClose }: ToolInspectorHostProps) {
  const sidebarCollapsed = useUiStore((s) => s.sidebarCollapsed);
  // 附着条件（§5.2 图标轨落地后）：64 图标轨 + 上下文栏(208，可收合) + 对话页 padding(32)
  // + 会话列表(240) + 间距(16) + 主回答 ≥640px + 检查器 380px
  const minAttachedWidth = 64 + (sidebarCollapsed ? 0 : 208) + 32 + 240 + 16 + 640 + 380;
  const attached = useMediaQuery(`(min-width: ${minAttachedWidth}px)`);
  const mobile = useMediaQuery("(max-width: 767px)");

  if (attached) {
    return <AttachedInspector turn={turn} selectedToolId={selectedToolId} onSelectTool={onSelectTool} onClose={onClose} />;
  }
  if (mobile) {
    return <BottomSheetInspector turn={turn} selectedToolId={selectedToolId} onSelectTool={onSelectTool} onClose={onClose} />;
  }
  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="sm:max-w-[420px]" aria-label="工具检查器">
        <SheetHeader>
          <SheetTitle>工具检查器</SheetTitle>
          <SheetDescription className="sr-only">查看本轮工具调用的参数、结果与来源</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 px-1">
          <ToolInspector turn={turn} selectedToolId={selectedToolId} onSelectTool={onSelectTool} />
        </div>
      </SheetContent>
    </Sheet>
  );
}

/** 宽屏附着面板：非模态，Escape 关闭并把焦点还给触发按钮。 */
function AttachedInspector({ turn, selectedToolId, onSelectTool, onClose }: ToolInspectorHostProps) {
  const triggerRef = useRef<Element | null>(null);

  useEffect(() => {
    triggerRef.current = document.activeElement;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(
    () => () => {
      const el = triggerRef.current;
      if (el instanceof HTMLElement && el.isConnected) el.focus();
    },
    [],
  );

  return (
    <aside
      aria-label="工具检查器"
      className="flex w-[380px] shrink-0 flex-col overflow-hidden border-l border-border bg-surface"
    >
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-border px-4">
        <span className="text-xs font-medium text-muted-foreground">工具检查器</span>
        <button
          type="button"
          onClick={onClose}
          title="关闭（Esc）"
          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1">
        <ToolInspector turn={turn} selectedToolId={selectedToolId} onSelectTool={onSelectTool} />
      </div>
    </aside>
  );
}

/** 移动端 Bottom Sheet：70dvh 默认，拖拽手柄可拉至 90dvh。 */
function BottomSheetInspector({ turn, selectedToolId, onSelectTool, onClose }: ToolInspectorHostProps) {
  const [heightDvh, setHeightDvh] = useState<70 | 90>(70);
  const dragStartY = useRef<number | null>(null);

  const onPointerDown = (e: React.PointerEvent) => {
    dragStartY.current = e.clientY;
  };
  const onPointerUp = (e: React.PointerEvent) => {
    if (dragStartY.current === null) return;
    const delta = e.clientY - dragStartY.current;
    dragStartY.current = null;
    if (delta < -40) setHeightDvh(90);
    else if (delta > 40) setHeightDvh(70);
  };

  return (
    <Sheet open onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="bottom" style={{ height: `${heightDvh}dvh` }} aria-label="工具检查器">
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="拖拽调整面板高度"
          onPointerDown={onPointerDown}
          onPointerUp={onPointerUp}
          className="flex h-6 shrink-0 cursor-grab items-center justify-center touch-none"
        >
          <span className="h-1 w-10 rounded-full bg-muted-foreground/30" />
        </div>
        <SheetHeader className="pt-0">
          <SheetTitle>工具检查器</SheetTitle>
          <SheetDescription className="sr-only">查看本轮工具调用的参数、结果与来源</SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 px-1">
          <ToolInspector turn={turn} selectedToolId={selectedToolId} onSelectTool={onSelectTool} />
        </div>
      </SheetContent>
    </Sheet>
  );
}
