import { useState } from 'react'
import { Loader2, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { PickedCanvasQuestion } from '@/api/canvas'

interface PickQuestionsPanelProps {
  subject: string
  loading: boolean
  onPick: (input: { requirement: string; subject?: string; count?: number }) => Promise<PickedCanvasQuestion[]>
  onAdd: (questions: PickedCanvasQuestion[]) => void
}

export function PickQuestionsPanel({ subject, loading, onPick, onAdd }: PickQuestionsPanelProps) {
  const [requirement, setRequirement] = useState('')
  const [count, setCount] = useState('3')
  const [questions, setQuestions] = useState<PickedCanvasQuestion[]>([])

  const runPick = async () => {
    const req = requirement.trim()
    if (!req) return
    const picked = await onPick({
      requirement: req,
      subject: subject || undefined,
      count: Math.max(1, Math.min(10, Number(count) || 3)),
    })
    setQuestions(picked)
  }

  return (
    <aside className="aurora-canvas-pick-panel flex h-full w-80 shrink-0 flex-col">
      <div className="aurora-canvas-pick-header p-3">
        <div className="text-sm font-medium">AI 选题</div>
      </div>
      <div className="space-y-3 p-3">
        <Textarea
          value={requirement}
          onChange={(event) => setRequirement(event.target.value)}
          placeholder="例如：函数零点与导数综合，偏中难"
          className="aurora-canvas-pick-input min-h-24"
        />
        <Input
          value={count}
          onChange={(event) => setCount(event.target.value)}
          inputMode="numeric"
          className="aurora-canvas-pick-input"
        />
        <Button
          type="button"
          className="aurora-canvas-pick-action w-full"
          onClick={() => void runPick()}
          disabled={loading || !requirement.trim()}
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
          搜索题目
        </Button>
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-3">
        {questions.map((question) => (
          <button
            key={question.questionId}
            type="button"
            onClick={() => onAdd([question])}
            className="aurora-canvas-picked-question w-full p-3 text-left text-sm transition hover:bg-accent"
          >
            <div className="font-medium">{question.title}</div>
            {question.selectReason && <div className="mt-1 text-xs text-muted-foreground">{question.selectReason}</div>}
          </button>
        ))}
      </div>
    </aside>
  )
}
