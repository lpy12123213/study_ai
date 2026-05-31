import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, Layers, Plus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { BlueprintSlot } from '@/types'
import { SlotEditor } from '@/features/generation/paperCompose/components/SlotEditor'
import {
  defaultQuestionTypes,
  type QuestionTypeOption,
} from '@/features/generation/paperCompose/components/questionTypes'

export interface BlueprintSlotConfigProps {
  slots: BlueprintSlot[]
  totalQuestions: number
  totalScore: number
  showQuestionTypes: boolean
  onToggleQuestionTypes: () => void
  onAddSlot: (type: QuestionTypeOption) => void
  onUpdateSlot: (index: number, slot: BlueprintSlot) => void
  onRemoveSlot: (index: number) => void
}

export function BlueprintSlotConfig({
  slots,
  totalQuestions,
  totalScore,
  showQuestionTypes,
  onToggleQuestionTypes,
  onAddSlot,
  onUpdateSlot,
  onRemoveSlot,
}: BlueprintSlotConfigProps) {
  return (
    <Card className="surface-raised">
      <CardHeader className="flex flex-row items-center justify-between pb-3">
        <div className="flex items-center gap-2">
          <Layers className="h-5 w-5 text-muted-foreground" />
          <CardTitle className="text-base">题型配置</CardTitle>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <Badge variant="secondary" className="font-normal">
            {totalQuestions} 题
          </Badge>
          <Badge variant="secondary" className="font-normal">
            {totalScore} 分
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        <div className="space-y-1 mb-4">
          <AnimatePresence mode="popLayout">
            {slots.map((slot, index) => (
              <SlotEditor
                key={slot.id}
                slot={slot}
                onUpdate={(s) => onUpdateSlot(index, s)}
                onRemove={() => onRemoveSlot(index)}
              />
            ))}
          </AnimatePresence>

          {slots.length === 0 && (
            <div className="text-center py-8 text-muted-foreground text-sm border border-dashed rounded-lg">
              暂无题型，请添加
            </div>
          )}
        </div>

        <div className="relative">
          <Button
            variant="outline"
            className="w-full justify-center gap-2 border-dashed hover:border-solid hover:bg-muted/50"
            onClick={onToggleQuestionTypes}
          >
            <Plus className="h-4 w-4" />
            添加题型
            <ChevronDown className={cn('h-4 w-4 transition-transform', showQuestionTypes && 'rotate-180')} />
          </Button>

          <AnimatePresence>
            {showQuestionTypes && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="absolute top-full left-0 right-0 mt-2 p-2 bg-popover border border-border rounded-lg shadow-lg z-10"
              >
                <div className="grid grid-cols-3 gap-2">
                  {defaultQuestionTypes.map((type) => (
                    <Button
                      key={type.id}
                      variant="ghost"
                      className="justify-start h-9"
                      onClick={() => onAddSlot(type)}
                    >
                      {type.name}
                    </Button>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </CardContent>
    </Card>
  )
}
