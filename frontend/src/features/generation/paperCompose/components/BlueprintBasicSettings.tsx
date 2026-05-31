import { AlertTriangle, Loader2, Settings2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Subject } from '@/types'
import type { SubjectFilters } from '@/api/subjects'
import type { BlueprintMode } from '@/features/generation/paperCompose/hooks/useBlueprintDraft'

export interface BlueprintBasicSettingsProps {
  mode: BlueprintMode
  subjects: Subject[] | undefined
  subject: string
  onSubjectChange: (value: string) => void
  topic: string
  onTopicChange: (value: string) => void
  filters: SubjectFilters | undefined
  isFiltersLoading: boolean
  isFiltersFetching: boolean
  filtersError: unknown
  onRefetchFilters: () => void
  gradeId: string
  onGradeChange: (value: string) => void
  textbookVersionId: string
  onTextbookVersionChange: (value: string) => void
}

export function BlueprintBasicSettings({
  mode,
  subjects,
  subject,
  onSubjectChange,
  topic,
  onTopicChange,
  filters,
  isFiltersLoading,
  isFiltersFetching,
  filtersError,
  onRefetchFilters,
  gradeId,
  onGradeChange,
  textbookVersionId,
  onTextbookVersionChange,
}: BlueprintBasicSettingsProps) {
  return (
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
          <Select value={subject} onValueChange={onSubjectChange}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder="选择学科" />
            </SelectTrigger>
            <SelectContent>
              {(subjects || [])
                .filter((s) => (s.code || '').trim().length > 0)
                .map((s) => (
                  <SelectItem key={s.id} value={s.code}>
                    {s.name}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </div>

        <div>
          <label className="text-sm font-medium mb-1.5 block">考查主题</label>
          <Input
            placeholder="如：导数 / 函数 / 圆锥曲线 / 阅读理解"
            value={topic}
            onChange={(e) => onTopicChange(e.target.value)}
          />
        </div>

        {mode === 'blueprint' && !!subject && isFiltersLoading && (
          <div className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground flex items-center gap-2">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在初始化筛选项，首次加载该学科可能需要几秒。
          </div>
        )}

        {mode === 'blueprint' && !!subject && !!filtersError && (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm flex items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-amber-700 dark:text-amber-300">
              <AlertTriangle className="h-4 w-4" />
              筛选项加载失败，可重试后继续组卷。
            </div>
            <Button type="button" variant="outline" size="sm" onClick={onRefetchFilters}>
              重试
            </Button>
          </div>
        )}

        {mode === 'blueprint' && !!subject && !isFiltersLoading && !filtersError && isFiltersFetching && (
          <div className="text-xs text-muted-foreground">正在刷新筛选项缓存...</div>
        )}

        {mode === 'blueprint' && filters && (
          <div className="grid grid-cols-2 gap-4">
            {filters.grades && (
              <div>
                <label className="text-sm font-medium mb-1.5 block">年级</label>
                <Select value={gradeId} onValueChange={onGradeChange}>
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
                <Select value={textbookVersionId} onValueChange={onTextbookVersionChange}>
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
  )
}
