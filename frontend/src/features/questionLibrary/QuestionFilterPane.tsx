import { RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Subject } from '@/types'
import type { QuestionOrigin } from '@/api/questionLibrary'

interface Props {
  subjects: Subject[]
  subject: string
  onSubjectChange: (value: string) => void
  origin: QuestionOrigin | 'all'
  onOriginChange: (value: QuestionOrigin | 'all') => void
  hidden: '0' | '1' | 'all'
  onHiddenChange: (value: '0' | '1' | 'all') => void
  q: string
  onQueryChange: (value: string) => void
  sort: 'updated_at' | 'ai_score'
  order: 'desc' | 'asc'
  onSortChange: (value: 'updated_at' | 'ai_score') => void
  onOrderChange: (value: 'desc' | 'asc') => void
  onRefresh: () => void
}

export function QuestionFilterPane(props: Props) {
  const {
    subjects,
    subject,
    onSubjectChange,
    origin,
    onOriginChange,
    hidden,
    onHiddenChange,
    q,
    onQueryChange,
    sort,
    order,
    onSortChange,
    onOrderChange,
    onRefresh,
  } = props

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="p-4 border-b">
        <div className="flex items-center justify-between gap-2">
          <div className="text-sm font-medium">筛选</div>
          <Button type="button" variant="ghost" size="icon" className="h-8 w-8" onClick={onRefresh}>
            <RotateCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-4 space-y-4">
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">学科</div>
          <Select value={subject} onValueChange={onSubjectChange}>
            <SelectTrigger className="h-9">
              <SelectValue placeholder="选择学科" />
            </SelectTrigger>
            <SelectContent>
              {(subjects || []).map((s) => (
                <SelectItem key={s.code} value={s.code}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">来源</div>
          <Select value={origin} onValueChange={(v) => onOriginChange(v as any)}>
            <SelectTrigger className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              <SelectItem value="crawled">爬取题</SelectItem>
              <SelectItem value="ai">AI 出题</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">显示</div>
          <Select value={hidden} onValueChange={(v) => onHiddenChange(v as any)}>
            <SelectTrigger className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">未隐藏</SelectItem>
              <SelectItem value="1">已隐藏</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">搜索题干</div>
          <Input
            value={q}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="关键词…"
            className="h-9"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">排序</div>
            <Select value={sort} onValueChange={(v) => onSortChange(v as any)}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="updated_at">更新时间</SelectItem>
                <SelectItem value="ai_score">AI 分数</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <div className="text-xs text-muted-foreground">顺序</div>
            <Select value={order} onValueChange={(v) => onOrderChange(v as any)}>
              <SelectTrigger className="h-9">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="desc">降序</SelectItem>
                <SelectItem value="asc">升序</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>
    </div>
  )
}

