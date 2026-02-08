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
  Settings2,
  Layers,
  ArrowRight,
  CheckCircle2
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Progress } from '@/components/ui/progress'
import { TaskTimeline } from '@/components/task/TaskTimeline'
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
    <div className="grid grid-cols-12 gap-3 items-center py-3 border-b border-border/50 last:border-0 text-sm hover:bg-muted/30 transition-colors px-2 rounded-md">
      <div className="col-span-3 font-medium">{slot.questionType}</div>
      <div className="col-span-3">
        <div className="flex items-center gap-2">
           <span className="text-xs text-muted-foreground w-8">数量</span>
           <Input
            type="number"
            min={1}
            max={50}
            value={slot.count}
            onChange={(e) => onUpdate({ ...slot, count: parseInt(e.target.value) || 1 })}
            className="h-8"
          />
        </div>
      </div>
      <div className="col-span-3">
        <div className="flex items-center gap-2">
           <span className="text-xs text-muted-foreground w-8">分值</span>
           <Input
            type="number"
            min={1}
            max={100}
            value={slot.score || 0}
            onChange={(e) => onUpdate({ ...slot, score: parseInt(e.target.value) || 0 })}
            className="h-8"
          />
        </div>
      </div>
      <div className="col-span-2">
        <Select
          value={slot.difficulty || 'medium'}
          onValueChange={(value) => onUpdate({ ...slot, difficulty: value })}
        >
          <SelectTrigger className="h-8 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="easy">简单</SelectItem>
            <SelectItem value="medium">中等</SelectItem>
            <SelectItem value="hard">困难</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-1 text-right">
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </div>
  )
}

export default function BlueprintPage() {
  const [subject, setSubject] = useState('')
  const [slots, setSlots] = useState<BlueprintSlot[]>([])
  const [blueprintName, setBlueprintName] = useState('')
  const [showQuestionTypes, setShowQuestionTypes] = useState(false)

  const { data: subjects } = useSubjects()
  const { data: filters } = useSubjectFilters(subject || undefined)
  const { compose, pause, resume, isComposing, result, taskId } = useComposePaper()
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
  const progress = taskSteps.length > 0 
    ? (taskSteps.filter((s) => s.status === 'completed').length / taskSteps.length) * 100 
    : 0

  return (
    <div className="h-full grid grid-cols-12 overflow-hidden">
      {/* Left Panel: Configuration */}
      <div className="col-span-7 h-full overflow-auto border-r border-border bg-background p-6">
        <div className="max-w-3xl mx-auto space-y-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight mb-2">蓝图组卷</h1>
            <p className="text-muted-foreground">
              配置试卷结构，AI 将自动搜索并组合题目
            </p>
          </div>

          <Card className="surface-raised">
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Settings2 className="h-5 w-5 text-muted-foreground" />
                <CardTitle className="text-base">基本设置</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-sm font-medium mb-1.5 block">学科</label>
                <Select
                  value={subject}
                  onValueChange={setSubject}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="选择学科" />
                  </SelectTrigger>
                  <SelectContent>
                    {subjects?.map((s) => (
                      <SelectItem key={s.id} value={s.code}>
                        {s.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {filters && (
                <div className="grid grid-cols-2 gap-4">
                  {filters.grades && (
                    <div>
                      <label className="text-sm font-medium mb-1.5 block">年级</label>
                      <Select>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="全部年级" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">全部年级</SelectItem>
                          {filters.grades.map((g) => (
                            <SelectItem key={String(g.id)} value={String(g.id)}>
                              {g.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  {filters.textbookVersions && (
                    <div>
                      <label className="text-sm font-medium mb-1.5 block">教材版本</label>
                      <Select>
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="全部版本" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">全部版本</SelectItem>
                          {filters.textbookVersions.map((v) => (
                            <SelectItem key={String(v.id)} value={String(v.id)}>
                              {v.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

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
                      onUpdate={(s) => handleUpdateSlot(index, s)}
                      onRemove={() => handleRemoveSlot(index)}
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
                      <div className="grid grid-cols-3 gap-2">
                        {defaultQuestionTypes.map((type) => (
                          <Button
                            key={type.id}
                            variant="ghost"
                            className="justify-start h-9"
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

          <div className="flex items-center gap-3 pt-4 border-t border-border">
            <div className="flex-1 flex items-center gap-2">
              <Input
                placeholder="蓝图名称"
                value={blueprintName}
                onChange={(e) => setBlueprintName(e.target.value)}
                className="max-w-[240px]"
              />
              <Button
                variant="ghost"
                onClick={handleSaveBlueprint}
                disabled={!blueprintName || !subject || slots.length === 0 || isSaving}
              >
                <Save className="h-4 w-4 mr-2" />
                保存
              </Button>
            </div>

            {isComposing ? (
              <Button variant="destructive" onClick={pause} className="w-32">
                <Pause className="h-4 w-4 mr-2" />
                暂停
              </Button>
            ) : isPaused ? (
              <Button onClick={resume} className="w-32 bg-primary text-primary-foreground hover:bg-primary/90">
                <Play className="h-4 w-4 mr-2" />
                继续
              </Button>
            ) : (
              <Button
                onClick={handleCompose}
                disabled={!subject || slots.length === 0}
                className="w-32 bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
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
        </div>
      </div>

      {/* Right Panel: Preview & Timeline */}
      <div className="col-span-5 h-full bg-sidebar-background border-l border-border flex flex-col overflow-hidden">
        <div className="p-6 border-b border-border">
          <h3 className="font-semibold mb-4 flex items-center gap-2">
            <Loader2 className={cn("h-4 w-4", isComposing && "animate-spin")} />
            任务执行
          </h3>
          
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>进度</span>
              <span>{Math.round(progress)}%</span>
            </div>
            <Progress value={progress} className="h-2" />
          </div>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-6">
             {result ? (
               <div className="text-center py-10">
                 <div className="h-16 w-16 bg-green-100 dark:bg-green-900/20 rounded-full flex items-center justify-center mx-auto mb-4">
                   <CheckCircle2 className="h-8 w-8 text-green-600 dark:text-green-400" />
                 </div>
                 <h3 className="text-lg font-medium mb-2">组卷完成</h3>
                 <p className="text-muted-foreground mb-6">
                   已生成试卷，包含 {result.questions.length} 道题目
                 </p>
                 <Button asChild className="gap-2">
                   <Link to={`/papers/${result.id}`}>
                     查看试卷 <ArrowRight className="h-4 w-4" />
                   </Link>
                 </Button>
               </div>
             ) : (
               <TaskTimeline steps={taskSteps} />
             )}
          </div>
        </ScrollArea>
      </div>
    </div>
  )
}
