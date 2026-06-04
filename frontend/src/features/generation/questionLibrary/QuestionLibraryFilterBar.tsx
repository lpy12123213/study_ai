import { RotateCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Subject } from '@/types'
import type { QuestionLibraryFilters } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'

interface Props {
  subjects: Subject[]
  filters: QuestionLibraryFilters
  onSubjectChange: (value: string) => void
  onOriginChange: (value: QuestionLibraryFilters['origin']) => void
  onHiddenChange: (value: QuestionLibraryFilters['hidden']) => void
  onQueryChange: (value: string) => void
  onSortChange: (value: QuestionLibraryFilters['sort']) => void
  onOrderChange: (value: QuestionLibraryFilters['order']) => void
  onRefresh: () => void
}

export function QuestionLibraryFilterBar(props: Props) {
  const {
    subjects,
    filters,
    onSubjectChange,
    onOriginChange,
    onHiddenChange,
    onQueryChange,
    onSortChange,
    onOrderChange,
    onRefresh,
  } = props

  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="w-[200px]">
        <div className="text-xs text-muted-foreground mb-2">学科</div>
        <Select value={filters.subject} onValueChange={onSubjectChange}>
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

      <div className="w-[140px]">
        <div className="text-xs text-muted-foreground mb-2">来源</div>
        <Select value={filters.origin} onValueChange={(v) => onOriginChange(v as any)}>
          <SelectTrigger className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="crawled">爬取题</SelectItem>
            <SelectItem value="ai">AI 题</SelectItem>
            <SelectItem value="media">图片/PDF</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="w-[140px]">
        <div className="text-xs text-muted-foreground mb-2">显示</div>
        <Select value={filters.hidden} onValueChange={(v) => onHiddenChange(v as any)}>
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

      <div className="flex-1 min-w-[240px]">
        <div className="text-xs text-muted-foreground mb-2">搜索题干</div>
        <Input value={filters.q} onChange={(e) => onQueryChange(e.target.value)} placeholder="关键词…" className="h-9" />
      </div>

      <div className="w-[140px]">
        <div className="text-xs text-muted-foreground mb-2">排序</div>
        <Select value={filters.sort} onValueChange={(v) => onSortChange(v as any)}>
          <SelectTrigger className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="updated_at">更新时间</SelectItem>
            <SelectItem value="ai_score">AI 分数</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div className="w-[120px]">
        <div className="text-xs text-muted-foreground mb-2">顺序</div>
        <Select value={filters.order} onValueChange={(v) => onOrderChange(v as any)}>
          <SelectTrigger className="h-9">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="desc">降序</SelectItem>
            <SelectItem value="asc">升序</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Button type="button" variant="outline" size="icon" className="h-9 w-9" onClick={onRefresh} aria-label="Refresh">
        <RotateCw className="h-4 w-4" />
      </Button>
    </div>
  )
}

