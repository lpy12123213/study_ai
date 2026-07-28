import { Check, ListTree, PencilLine } from "lucide-react";

import { Button } from "@/components/ui/button";

interface SemanticConfirmationProps {
  onConfirm: () => void;
  onRevise: () => void;
  onViewCandidates: () => void;
  disabled?: boolean;
}

/**
 * 语义确认快捷操作（视觉规划 §9.1）。
 * 仅在上一轮已提出 <EXAM_PAPER_PLAN> 方案且当前无生成时显示。
 * 本质是发送普通用户消息 + 结构化 intent（服务端确定性判定，不再依赖确认词子串）。
 */
export function SemanticConfirmation({ onConfirm, onRevise, onViewCandidates, disabled }: SemanticConfirmationProps) {
  return (
    <div
      role="group"
      aria-label="组卷方案快捷操作"
      className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-spectral/30 bg-surface-mist px-3 py-2.5"
    >
      <span className="text-xs text-muted-foreground">已提出组卷方案：</span>
      <Button size="sm" onClick={onConfirm} disabled={disabled}>
        <Check />
        确认并创建
      </Button>
      <Button size="sm" variant="outline" onClick={onRevise} disabled={disabled}>
        <PencilLine />
        修改方案
      </Button>
      <Button size="sm" variant="outline" onClick={onViewCandidates} disabled={disabled}>
        <ListTree />
        先看候选题
      </Button>
      <span className="w-full text-[11px] text-muted-foreground sm:w-auto">
        以普通消息发送，可在输入框继续编辑补充。
      </span>
    </div>
  );
}
