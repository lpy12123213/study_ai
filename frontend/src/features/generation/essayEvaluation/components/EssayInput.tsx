import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RichTextarea } from '@/components/shared/RichTextarea'
import type {
  EssayEvaluationRequest,
  EssayLanguage,
  EssayType,
  GradeBand,
} from '@/api/essayEvaluations'

const ESSAY_TYPES: Array<{ value: EssayType; label: string }> = [
  { value: 'argumentative', label: '议论文' },
  { value: 'narrative', label: '记叙文' },
  { value: 'expository', label: '说明文' },
  { value: 'applied', label: '应用文' },
  { value: 'other', label: '其他' },
]

const GRADE_BANDS: Array<{ value: GradeBand; label: string }> = [
  { value: 'primary', label: '小学' },
  { value: 'junior', label: '初中' },
  { value: 'senior', label: '高中' },
  { value: 'ielts', label: '雅思' },
  { value: 'toefl', label: '托福' },
  { value: 'other', label: '其他' },
]

const LANGUAGES: Array<{ value: EssayLanguage; label: string }> = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
]

export type EssayInputProps = {
  loading?: boolean
  onSubmit: (payload: EssayEvaluationRequest) => void
}

/**
 * Composer for the essay-evaluation page.
 *
 * Captures the essay text plus subject / type / language metadata. The form
 * is intentionally minimal so it composes with the surrounding wide-layout
 * page (sidebar + result + history); pages may wrap it in a ``<Card>`` for
 * consistency with the rest of the workspace.
 */
export function EssayInput({ loading, onSubmit }: EssayInputProps) {
  const [text, setText] = useState('')
  const [subject, setSubject] = useState('语文')
  const [topic, setTopic] = useState('')
  const [language, setLanguage] = useState<EssayLanguage>('zh')
  const [essayType, setEssayType] = useState<EssayType>('argumentative')
  const [gradeBand, setGradeBand] = useState<GradeBand>('senior')
  const [rubricMaxScore, setRubricMaxScore] = useState(60)
  const [rubricMaxScoreText, setRubricMaxScoreText] = useState('60')
  const [requirements, setRequirements] = useState('')

  const commitRubricMaxScore = () => {
    const parsed = Number.parseInt(rubricMaxScoreText, 10)
    const next = Number.isFinite(parsed) ? Math.max(10, Math.min(150, parsed)) : rubricMaxScore
    setRubricMaxScore(next)
    setRubricMaxScoreText(String(next))
    return next
  }

  const handleSubmit = () => {
    const cleaned = text.trim()
    if (cleaned.length < 10) {
      return
    }
    const maxScore = commitRubricMaxScore()
    onSubmit({
      text: cleaned,
      subject: subject.trim() || '语文',
      topic: topic.trim(),
      language,
      essay_type: essayType,
      grade_band: gradeBand,
      rubric_max_score: maxScore,
      requirements: requirements.trim(),
    })
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="essay-subject">
            学科
          </label>
          <Input
            id="essay-subject"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="语文 / 英语 / ..."
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="essay-topic">
            题目
          </label>
          <Input
            id="essay-topic"
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="可选：作文题目或材料"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="essay-language">
            语言
          </label>
          <select
            id="essay-language"
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={language}
            onChange={(event) => setLanguage(event.target.value as EssayLanguage)}
          >
            {LANGUAGES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="essay-type">
            文体
          </label>
          <select
            id="essay-type"
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={essayType}
            onChange={(event) => setEssayType(event.target.value as EssayType)}
          >
            {ESSAY_TYPES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="essay-grade-band">
            年段
          </label>
          <select
            id="essay-grade-band"
            className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            value={gradeBand}
            onChange={(event) => setGradeBand(event.target.value as GradeBand)}
          >
            {GRADE_BANDS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-1">
        <label className="text-xs text-muted-foreground">
          作文正文
        </label>
        <RichTextarea
          value={text}
          onChange={setText}
          ariaLabel="作文正文"
          debounceMs={0}
          minHeight={260}
          maxHeight={520}
          placeholder="将作文粘贴或输入到这里，至少 10 个字。"
          spellCheck={language === 'en'}
        />
      </div>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="space-y-1">
          <label className="text-xs text-muted-foreground" htmlFor="essay-rubric-max">
            评分总分
          </label>
          <Input
            id="essay-rubric-max"
            type="number"
            min={10}
            max={150}
            value={rubricMaxScoreText}
            onChange={(event) => setRubricMaxScoreText(event.target.value)}
            onBlur={commitRubricMaxScore}
          />
        </div>
        <div className="space-y-1 md:col-span-2">
          <label className="text-xs text-muted-foreground" htmlFor="essay-requirements">
            评分要求（可选）
          </label>
          <Input
            id="essay-requirements"
            value={requirements}
            onChange={(event) => setRequirements(event.target.value)}
            placeholder="例如：注重逻辑论证；按高考语文标准。"
          />
        </div>
      </div>

      <div className="flex justify-end">
        <Button type="button" onClick={handleSubmit} disabled={loading || text.trim().length < 10}>
          {loading ? '批改中…' : '开始批改'}
        </Button>
      </div>
    </div>
  )
}
