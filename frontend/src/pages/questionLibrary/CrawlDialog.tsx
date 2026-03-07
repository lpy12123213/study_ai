import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
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
    query: string
    difficulty: string
    limit: number
    max_pages: number
    min_quality_score: number
    difficulty_value_min?: number
    difficulty_value_max?: number
    require_difficulty_value?: boolean
  }) => void
}

const DIFFICULTY_ANY = '__any__'

export function CrawlDialog(props: Props) {
  const { open, onOpenChange, subject, onSubmit } = props

  const [query, setQuery] = useState('')
  const [difficulty, setDifficulty] = useState(DIFFICULTY_ANY)
  const [limit, setLimit] = useState('30')
  const [maxPages, setMaxPages] = useState('2')
  const [minQuality, setMinQuality] = useState('0')
  const [difficultyValueMin, setDifficultyValueMin] = useState('')
  const [difficultyValueMax, setDifficultyValueMax] = useState('')
  const [requireDifficultyValue, setRequireDifficultyValue] = useState(true)

  const canSubmit = useMemo(() => {
    const q = query.trim()
    if (!q) return false
    if (!subject.trim()) return false
    return true
  }, [query, subject])

  const submit = () => {
    if (!canSubmit) return
    const q = query.trim()

    const lim = Number(limit)
    const mp = Number(maxPages)
    const mq = Number(minQuality)
    const dvMinRaw = Number(difficultyValueMin)
    const dvMaxRaw = Number(difficultyValueMax)

    const dvMinParsed = Number.isFinite(dvMinRaw) ? Math.max(0, Math.min(1, dvMinRaw)) : undefined
    const dvMaxParsed = Number.isFinite(dvMaxRaw) ? Math.max(0, Math.min(1, dvMaxRaw)) : undefined
    let dvMin = dvMinParsed
    let dvMax = dvMaxParsed
    if (typeof dvMin === 'number' && typeof dvMax === 'number' && dvMin > dvMax) {
      const tmp = dvMin
      dvMin = dvMax
      dvMax = tmp
    }

    const hasDvRange = typeof dvMin === 'number' || typeof dvMax === 'number'

    onSubmit({
      query: q,
      difficulty: difficulty === DIFFICULTY_ANY ? '' : difficulty,
      limit: Number.isFinite(lim) ? Math.max(1, Math.min(200, Math.floor(lim))) : 30,
      max_pages: Number.isFinite(mp) ? Math.max(1, Math.min(50, Math.floor(mp))) : 2,
      min_quality_score: Number.isFinite(mq) ? Math.max(0, Math.min(100, Math.floor(mq))) : 0,
      difficulty_value_min: dvMin,
      difficulty_value_max: dvMax,
      require_difficulty_value: hasDvRange ? Boolean(requireDifficultyValue) : undefined,
    })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <DialogHeader>
          <DialogTitle>爬取入库</DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <div className="text-xs text-muted-foreground mb-2">学科</div>
            <div className="text-sm font-medium">{subject}</div>
          </div>

          <div>
            <div className="text-xs text-muted-foreground mb-2">关键词</div>
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="例如：函数 单调性" />
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
              <Input value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="30" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-muted-foreground mb-2">最大页数</div>
              <Input value={maxPages} onChange={(e) => setMaxPages(e.target.value)} placeholder="2" />
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-2">最低质量分</div>
              <Input value={minQuality} onChange={(e) => setMinQuality(e.target.value)} placeholder="0" />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-xs text-muted-foreground mb-2">难度系数最小值（可选）</div>
              <Input value={difficultyValueMin} onChange={(e) => setDifficultyValueMin(e.target.value)} placeholder="例如：0.40" />
            </div>
            <div>
              <div className="text-xs text-muted-foreground mb-2">难度系数最大值（可选）</div>
              <Input value={difficultyValueMax} onChange={(e) => setDifficultyValueMax(e.target.value)} placeholder="例如：0.75" />
            </div>
          </div>

          <div className="flex items-center justify-between gap-3 rounded-lg border p-3">
            <div className="min-w-0">
              <div className="text-sm font-medium">严格难度系数</div>
              <div className="text-xs text-muted-foreground">勾选后仅保留带难度系数且落在范围内的题目</div>
            </div>
            <Switch checked={requireDifficultyValue} onCheckedChange={(v: boolean) => setRequireDifficultyValue(Boolean(v))} />
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button type="button" onClick={submit} disabled={!canSubmit}>
            <Loader2 className="h-4 w-4 mr-2 opacity-0" />
            开始
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

