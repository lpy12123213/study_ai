import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Trash2,
  Play,
  Pause,
  FileText,
  Loader2,
  ChevronDown,
  Save,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { ProgressIndicator } from '@/components/task/ProgressIndicator'
import { useComposePaper, useSaveBlueprint } from '@/hooks/useBlueprint'
import { useSubjects, useSubjectFilters } from '@/hooks/useSubjects'
import { useTaskStore } from '@/stores/useTaskStore'
import { cn, generateId } from '@/lib/utils'
import type { BlueprintSlot } from '@/types'

const defaultQuestionTypes = [
  { id: 'single_choice', name: '单选题', defaultScore: 3 },
  { id: 'multi_choice', name: '多选题', defaultScore: 4 },
  { id: 'fill_blank', name: '填空题', defaultScore: 4 },
  { id: 'short_answer', name: '简答题', defaultScore: 8 },
  { id: 'calculation', name: '计算题', defaultScore: 10 },
  { id: 'essay', name: '论述题', defaultScore: 12 },
]

interface SlotEditorProps {
  slot: BlueprintSlot
  onUpdate: (slot: BlueprintSlot) => void
  onRemove: () => void
}

function SlotEditor({ slot, onUpdate, onRemove }: SlotEditorProps) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="border border-border rounded-lg p-4 mb-3"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="font-medium text-sm">{slot.questionType}</span>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div>
          <label className="text-xs text-muted-foreground">数量</label>
          <Input
            type="number"
            min={1}
            max={50}
            value={slot.count}
            onChange={(e) =>
              onUpdate({ ...slot, count: parseInt(e.target.value) || 1 })
            }
            className="h-8 mt-1"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">每题分值</label>
          <Input
            type="number"
            min={1}
            max={100}
            value={slot.score || 0}
            onChange={(e) =>
              onUpdate({ ...slot, score: parseInt(e.target.value) || 0 })
            }
            className="h-8 mt-1"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground">难度</label>
          <select
            value={slot.difficulty || 'medium'}
            onChange={(e) => onUpdate({ ...slot, difficulty: e.target.value })}
            className="w-full h-8 mt-1 rounded-md border border-input bg-background px-2 text-sm"
          >
            <option value="easy">简单</option>
            <option value="medium">中等</option>
            <option value="hard">困难</option>
          </select>
        </div>
      </div>
    </motion.div>
  )
}

export default function BlueprintPage() {
  const [subject, setSubject] = useState('')
  const [slots, setSlots] = useState<BlueprintSlot[]>([])
  const [blueprintName, setBlueprintName] = useState('')
  const [showQuestionTypes, setShowQuestionTypes] = useState(false)

  const { data: subjects } = useSubjects()
  const { data: filters } = useSubjectFilters(subject || undefined)
  const { compose, pause, resume, isComposing, result, error, taskId } =
    useComposePaper()
  const { mutate: saveBlueprint, isPending: isSaving } = useSaveBlueprint()

  const taskSteps = useTaskStore((state) => state.getTaskSteps(taskId ?? ''))
  const checkpoint = useTaskStore((state) =>
    taskId ? state.getCheckpoint(taskId) : undefined
  )

  const totalScore = slots.reduce(
    (sum, slot) => sum + slot.count * (slot.score || 0),
    0
  )
  const totalQuestions = slots.reduce((sum, slot) => sum + slot.count, 0)

  const handleAddSlot = (type: { id: string; name: string; defaultScore: number }) => {
    const newSlot: BlueprintSlot = {
      id: generateId(),
      questionType: type.name,
      count: 5,
      score: type.defaultScore,
      difficulty: 'medium',
    }
    setSlots([...slots, newSlot])
    setShowQuestionTypes(false)
  }

  const handleUpdateSlot = (index: number, slot: BlueprintSlot) => {
    const newSlots = [...slots]
    newSlots[index] = slot
    setSlots(newSlots)
  }

  const handleRemoveSlot = (index: number) => {
    setSlots(slots.filter((_, i) => i !== index))
  }

  const handleCompose = () => {
    if (!subject || slots.length === 0) return
    compose({ subject, slots })
  }

  const handleSaveBlueprint = () => {
    if (!blueprintName || !subject || slots.length === 0) return
    saveBlueprint({ name: blueprintName, subject, slots })
    setBlueprintName('')
  }

  const isPaused = checkpoint?.status === 'paused'

  return (
    <div className="h-full flex">
      <div className="flex-1 p-6 overflow-auto">
        <div className="max-w-3xl mx-auto">
          <div className="mb-6">
            <h1 className="text-2xl font-bold mb-2">蓝图组卷</h1>
            <p className="text-muted-foreground">
              配置试卷结构，AI 将自动搜索并组合题目
            </p>
          </div>

          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="text-lg">基本设置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium">学科</label>
                <select
                  value={subject}
                  onChange={(e) => setSubject(e.target.value)}
                  className="w-full h-10 mt-1 rounded-md border border-input bg-background px-3"
                >
                  <option value="">选择学科</option>
                  {subjects?.map((s) => (
                    <option key={s.id} value={s.code}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>

              {filters && (
                <div className="grid grid-cols-2 gap-4">
                  {filters.grades && (
                    <div>
                      <label className="text-sm font-medium">年级</label>
                      <select className="w-full h-10 mt-1 rounded-md border border-input bg-background px-3">
                        <option value="">全部年级</option>
                        {filters.grades.map((g) => (
                          <option key={g.id} value={g.id}>
                            {g.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                  {filters.textbookVersions && (
                    <div>
                      <label className="text-sm font-medium">教材版本</label>
                      <select className="w-full h-10 mt-1 rounded-md border border-input bg-background px-3">
                        <option value="">全部版本</option>
                        {filters.textbookVersions.map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="mb-6">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-lg">题型配置</CardTitle>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>{totalQuestions} 题</span>
                <Separator orientation="vertical" className="h-4" />
                <span>{totalScore} 分</span>
              </div>
            </CardHeader>
            <CardContent>
              <AnimatePresence mode="popLayout">
                {slots.map((slot, index) => (
                  <SlotEditor
                    key={slot.id}
                    slot={slot}
                    onUpdate={(s) => handleUpdateSlot(index, s)}
                    onRemove={() => handleRemoveSlot(index)}
                  />
                ))}
              </AnimatePresence>

              <div className="relative">
                <Button
                  variant="outline"
                  className="w-full justify-center gap-2"
                  onClick={() => setShowQuestionTypes(!showQuestionTypes)}
                >
                  <Plus className="h-4 w-4" />
                  添加题型
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 transition-transform",
                      showQuestionTypes && "rotate-180"
                    )}
                  />
                </Button>

                <AnimatePresence>
                  {showQuestionTypes && (
                    <motion.div
                      initial={{ opacity: 0, y: -10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -10 }}
                      className="absolute top-full left-0 right-0 mt-2 p-2 bg-popover border border-border rounded-lg shadow-lg z-10"
                    >
                      <div className="grid grid-cols-2 gap-2">
                        {defaultQuestionTypes.map((type) => (
                          <Button
                            key={type.id}
                            variant="ghost"
                            className="justify-start"
                            onClick={() => handleAddSlot(type)}
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

          <div className="flex items-center gap-3">
            <div className="flex-1 flex items-center gap-2">
              <Input
                placeholder="蓝图名称"
                value={blueprintName}
                onChange={(e) => setBlueprintName(e.target.value)}
                className="max-w-[200px]"
              />
              <Button
                variant="outline"
                onClick={handleSaveBlueprint}
                disabled={!blueprintName || !subject || slots.length === 0 || isSaving}
              >
                <Save className="h-4 w-4 mr-2" />
                保存蓝图
              </Button>
            </div>

            {isComposing ? (
              <Button variant="destructive" onClick={pause}>
                <Pause className="h-4 w-4 mr-2" />
                暂停
              </Button>
            ) : isPaused ? (
              <Button onClick={resume}>
                <Play className="h-4 w-4 mr-2" />
                继续
              </Button>
            ) : (
              <Button
                onClick={handleCompose}
                disabled={!subject || slots.length === 0}
              >
                {isComposing ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <FileText className="h-4 w-4 mr-2" />
                )}
                开始组卷
              </Button>
            )}
          </div>

          {error && (
            <div className="mt-4 bg-destructive/10 border border-destructive/20 rounded-lg p-4">
              <p className="text-sm text-destructive">{error}</p>
            </div>
          )}

          {result && (
            <Card className="mt-6">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  组卷完成
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-muted-foreground mb-4">
                  试卷已生成，包含 {result.questions.length} 道题目
                </p>
                <Button asChild>
                  <Link to={`/papers/${result.id}`}>查看试卷</Link>
                </Button>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {(isComposing || isPaused || taskSteps.length > 0) && (
        <div className="w-[360px] border-l border-border glass">
          <div className="p-4 border-b border-border">
            <h3 className="font-semibold mb-2">组卷进度</h3>
            <ProgressIndicator
              current={taskSteps.filter((s) => s.status === 'completed').length}
              total={taskSteps.length || 1}
              status={isPaused ? 'paused' : isComposing ? 'running' : 'completed'}
            />
          </div>
          <ScrollArea className="h-[calc(100%-80px)]">
            <div className="p-4">
              <TaskTimeline steps={taskSteps} />
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}
