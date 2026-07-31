import { Plus, Trash2 } from "lucide-react";
import type { BlueprintSlot } from "@/shared/api/types";
import { DIFFICULTIES, QUESTION_TYPES } from "@/shared/api/types";
import { clamp } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toInt } from "../model/utils";


/** 题型槽位行编辑器（蓝图表单 / 手工配置共用）。 */
export function SlotsEditor({ slots, onChange }: { slots: BlueprintSlot[]; onChange: (slots: BlueprintSlot[]) => void }) {
  const update = (i: number, patch: Partial<BlueprintSlot>) =>
    onChange(slots.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  const remove = (i: number) => onChange(slots.filter((_, idx) => idx !== i));
  const add = () => onChange([...slots, { questionType: "单选题", count: 5, difficulty: "中等" }]);
  return (
    <div className="space-y-2">
      {slots.map((slot, i) => (
        <div key={i} className="flex items-center gap-2">
          <Select value={slot.questionType} onValueChange={(v) => update(i, { questionType: v })}>
            <SelectTrigger className="w-28">
              <SelectValue placeholder="题型" />
            </SelectTrigger>
            <SelectContent>
              {QUESTION_TYPES.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Input
            type="number"
            min={1}
            max={50}
            className="w-20"
            value={slot.count}
            onChange={(e) => update(i, { count: clamp(toInt(e.target.value, 1), 1, 50) })}
            aria-label="数量"
          />
          <Select
            value={slot.difficulty || "中等"}
            onValueChange={(v) => update(i, { difficulty: v })}
          >
            <SelectTrigger className="w-24">
              <SelectValue placeholder="难度" />
            </SelectTrigger>
            <SelectContent>
              {DIFFICULTIES.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            className="text-muted-foreground hover:text-destructive"
            onClick={() => remove(i)}
            aria-label="删除此行"
          >
            <Trash2 />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" onClick={add}>
        <Plus /> 添加一行
      </Button>
    </div>
  );
}

export function validSlots(slots: BlueprintSlot[]): BlueprintSlot[] {
  // 后端把空难度归为「中等」并作为检索过滤条件（_difficulty_from_slot），这里始终显式带上难度
  return slots
    .filter((s) => s.questionType && s.count > 0)
    .map((s) => ({ questionType: s.questionType, count: s.count, difficulty: s.difficulty || "中等" }));
}

