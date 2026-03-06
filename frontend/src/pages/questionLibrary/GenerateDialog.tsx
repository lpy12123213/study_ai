import { useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  subject: string
  onSubmit: (payload: {
    topic: string
    difficulty: string
    question_type: string
    count: number
    use_study_archive: boolean
  }) => void
}

const DIFFICULTY_ANY = '__any__'

export function GenerateDialog(props: Props) {
  const { open, onOpenChange, subject, onSubmit } = props

  const [topic, setTopic] = useState('')
  const [difficulty, setDifficulty] = useState(DIFFICULTY_ANY)
  const [questionType, setQuestionType] = useState('')
  const [count, setCount] = useState('5')
  const [useStudyArchive, setUseStudyArchive] = useState(true)

  const canSubmit = useMemo(() => {
    if (!subject.trim()) return false
    if (!topic.trim()) return false
    return true
  }, [subject, topic])

  const submit = () => {
    if (!canSubmit) return

    const n = Number(count)
    const finalCount = Number.isFinite(n) ? Math.max(1, Math.min(10, Math.floor(n))) : 5

    onSubmit({
      topic: topic.trim(),
      difficulty: difficulty === DIFFICULTY_ANY ? '' : difficulty,
      question_type: questionType.trim(),
      count: finalCount,
      use_study_archive: Boolean(useStudyArchive),
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>AI 出题</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <div className="text-xs text-muted-foreground mb-2">学科</div>
            <div className="text-sm font-medium">{subject}</div>
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-2">主题 / 知识点</div>
            <Input value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="例如：函数 单调性" />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-muted-foreground mb-2">难度</div>
              <Select value={difficulty} onValueChange={setDifficulty}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={DIFFICULTY_ANY}>不限</SelectItem>
                  <SelectItem value="简单">简单</SelectItem>
                  <SelectItem value="中等">中等</SelectItem>
                  <SelectItem value="困难">困难</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-2">数量</div>
              <Input value={count} onChange={(e) => setCount(e.target.value)} placeholder="5" />
              <div className="text-[11px] text-muted-foreground mt-1">上限 10</div>
            </div>
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-2">题型（可选）</div>
            <Input value={questionType} onChange={(e) => setQuestionType(e.target.value)} placeholder="例如：选择题 / 填空题 / 解答题" />
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
            <div className="min-w-0">
              <div className="text-sm font-medium">使用自学资料</div>
              <div className="text-xs text-muted-foreground">从 StudyArchive 提取上下文，提高生成质量</div>
            </div>
            <Switch checked={useStudyArchive} onCheckedChange={(v: boolean) => setUseStudyArchive(Boolean(v))} />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button type="button" onClick={submit} disabled={!canSubmit}>
            开始
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
