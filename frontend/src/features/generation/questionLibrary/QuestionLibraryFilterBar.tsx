import { CircleHelp, RotateCw, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type { Subject } from '@/types'
import type { QuestionLibraryFilters } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'

type MoreFilterKey = 'year' | 'region' | 'grade' | 'semester' | 'method'

interface FilterOption {
  value: string
  label: string
}

interface Props {
  subjects: Subject[]
  filters: QuestionLibraryFilters
  onSubjectChange: (value: string) => void
  onOriginChange: (value: QuestionLibraryFilters['origin']) => void
  onHiddenChange: (value: QuestionLibraryFilters['hidden']) => void
  onQueryChange: (value: string) => void
  onExamSceneChange: (value: string) => void
  onQuestionTypeChange: (value: string) => void
  onDifficultyChange: (value: string) => void
  onCategoryChange: (value: string) => void
  onMoreFilterChange: (key: MoreFilterKey, value: string) => void
  onOnlyNewChange: (value: boolean) => void
  onSortChange: (value: QuestionLibraryFilters['sort']) => void
  onOrderChange: (value: QuestionLibraryFilters['order']) => void
  onRefresh: () => void
}

const ALL_OPTION: FilterOption = { value: '', label: '全部' }

const SCENE_OPTIONS: FilterOption[] = [
  ALL_OPTION,
  { value: '预习', label: '预习' },
  { value: '作业', label: '作业' },
  { value: '单元测', label: '单元测' },
  { value: '阶段检测', label: '阶段检测' },
  { value: '期中', label: '期中' },
  { value: '期末', label: '期末' },
  { value: '开学考', label: '开学考' },
  { value: '模拟', label: '模拟' },
  { value: '真题', label: '真题' },
  { value: '学业考', label: '学业考' },
  { value: '假期', label: '假期' },
  { value: '竞赛', label: '竞赛' },
  { value: '强基', label: '强基' },
]

const QUESTION_TYPE_OPTIONS: FilterOption[] = [
  ALL_OPTION,
  { value: '单选题', label: '单选题' },
  { value: '多选题', label: '多选题' },
  { value: '填空题', label: '填空题' },
  { value: '解答题', label: '解答题' },
  { value: '判断题', label: '判断题' },
  { value: '概念填空', label: '概念填空' },
]

const DIFFICULTY_OPTIONS: FilterOption[] = [
  ALL_OPTION,
  { value: '容易', label: '容易' },
  { value: '适中', label: '适中' },
  { value: '困难', label: '困难' },
]

const CATEGORY_OPTIONS: FilterOption[] = [
  ALL_OPTION,
  { value: '典型题', label: '典型题' },
  { value: '压轴题', label: '压轴题' },
  { value: '同步题', label: '同步题' },
  { value: '新文化题', label: '新文化题' },
  { value: '课本原题', label: '课本原题' },
]

const YEAR_OPTIONS = ['2026', '2025', '2024', '2023', '2022', '2021', '2020']
const REGION_OPTIONS = [
  '北京',
  '上海',
  '天津',
  '重庆',
  '河北',
  '河南',
  '山东',
  '江苏',
  '浙江',
  '广东',
  '四川',
  '湖南',
  '湖北',
  '福建',
  '安徽',
  '江西',
  '辽宁',
  '陕西',
]
const GRADE_OPTIONS = ['高一', '高二', '高三', '初一', '初二', '初三']
const SEMESTER_OPTIONS = ['上学期', '下学期', '一模', '二模', '期中', '期末']
const METHOD_OPTIONS = ['分类讨论', '数形结合', '构造法', '转化化归', '函数与方程', '参数讨论']

function QuickFilterGroup(props: {
  label: string
  value: string
  options: FilterOption[]
  onChange: (value: string) => void
}) {
  const { label, value, options, onChange } = props
  const activeValue = String(value || '').trim()

  return (
    <div className="grid grid-cols-[64px_1fr] items-start gap-3">
      <div className="pt-1 text-sm text-muted-foreground sm:text-base">{label}</div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-6 gap-y-2">
        {options.map((option) => {
          const selected = activeValue === option.value
          return (
            <button
              key={`${label}-${option.label}`}
              type="button"
              className={cn(
                'aurora-question-filter-chip h-8 whitespace-nowrap px-2 text-left text-sm text-foreground sm:text-base',
                selected && 'aurora-question-filter-chip-active'
              )}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

function MoreSelect(props: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  const { label, value, options, onChange } = props
  const selectValue = value.trim() || '__all'

  return (
    <Select value={selectValue} onValueChange={(next) => onChange(next === '__all' ? '' : next)}>
      <SelectTrigger className="h-8 w-[108px] border-0 bg-transparent px-0 text-sm shadow-none focus:ring-0 sm:text-base">
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="__all">{label}</SelectItem>
        {options.map((option) => (
          <SelectItem key={`${label}-${option}`} value={option}>
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

export function QuestionLibraryFilterBar(props: Props) {
  const {
    subjects,
    filters,
    onSubjectChange,
    onOriginChange,
    onHiddenChange,
    onQueryChange,
    onExamSceneChange,
    onQuestionTypeChange,
    onDifficultyChange,
    onCategoryChange,
    onMoreFilterChange,
    onOnlyNewChange,
    onSortChange,
    onOrderChange,
    onRefresh,
  } = props

  return (
    <div className="aurora-question-filters space-y-3 p-4">
      <QuickFilterGroup
        label="场景："
        value={filters.examScene}
        options={SCENE_OPTIONS}
        onChange={onExamSceneChange}
      />
      <QuickFilterGroup
        label="题型："
        value={filters.questionType}
        options={QUESTION_TYPE_OPTIONS}
        onChange={onQuestionTypeChange}
      />
      <QuickFilterGroup
        label="难度："
        value={filters.difficulty}
        options={DIFFICULTY_OPTIONS}
        onChange={onDifficultyChange}
      />
      <QuickFilterGroup
        label="分类："
        value={filters.category}
        options={CATEGORY_OPTIONS}
        onChange={onCategoryChange}
      />

      <div className="grid grid-cols-[64px_1fr] items-start gap-3 border-t border-dashed border-border/70 pt-3">
        <div className="pt-1 text-sm text-muted-foreground sm:text-base">更多：</div>
        <div className="flex min-w-0 flex-wrap items-center gap-x-8 gap-y-2">
          <MoreSelect label="年份" value={filters.year} options={YEAR_OPTIONS} onChange={(v) => onMoreFilterChange('year', v)} />
          <MoreSelect label="地区" value={filters.region} options={REGION_OPTIONS} onChange={(v) => onMoreFilterChange('region', v)} />
          <MoreSelect label="年级" value={filters.grade} options={GRADE_OPTIONS} onChange={(v) => onMoreFilterChange('grade', v)} />
          <MoreSelect label="学期" value={filters.semester} options={SEMESTER_OPTIONS} onChange={(v) => onMoreFilterChange('semester', v)} />
          <MoreSelect label="考法" value={filters.method} options={METHOD_OPTIONS} onChange={(v) => onMoreFilterChange('method', v)} />
          <label className="relative flex h-8 items-center gap-2 whitespace-nowrap text-sm text-foreground sm:text-base">
            <Checkbox
              checked={filters.onlyNew}
              onCheckedChange={(checked) => onOnlyNewChange(Boolean(checked))}
              aria-label="只看新题"
            />
            <span>只看新题</span>
            <span className="absolute -top-3 left-3 rounded bg-orange-500 px-1 text-[10px] font-medium leading-4 text-white">
              new
            </span>
          </label>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  className="flex h-8 w-8 items-center justify-center text-muted-foreground hover:text-foreground"
                  aria-label="新题说明"
                >
                  <CircleHelp className="h-4 w-4" />
                </button>
              </TooltipTrigger>
              <TooltipContent>按最近 30 天入库或更新的题目筛选</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 pt-1">
        <div className="w-[180px]">
          <div className="mb-2 text-xs text-muted-foreground">学科</div>
          <Select value={filters.subject} onValueChange={onSubjectChange}>
            <SelectTrigger className="h-9 bg-background/45">
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

        <div className="w-[120px]">
          <div className="mb-2 text-xs text-muted-foreground">来源</div>
          <Select value={filters.origin} onValueChange={(v) => onOriginChange(v as any)}>
            <SelectTrigger className="h-9 bg-background/45">
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

        <div className="w-[120px]">
          <div className="mb-2 text-xs text-muted-foreground">显示</div>
          <Select value={filters.hidden} onValueChange={(v) => onHiddenChange(v as any)}>
            <SelectTrigger className="h-9 bg-background/45">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">未隐藏</SelectItem>
              <SelectItem value="1">已隐藏</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="min-w-[220px] flex-1">
          <div className="mb-2 text-xs text-muted-foreground">搜索题干</div>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={filters.q}
              onChange={(e) => onQueryChange(e.target.value)}
              placeholder="关键词…"
              className="h-9 bg-background/45 pl-9"
            />
          </div>
        </div>

        <div className="w-[120px]">
          <div className="mb-2 text-xs text-muted-foreground">排序</div>
          <Select value={filters.sort} onValueChange={(v) => onSortChange(v as any)}>
            <SelectTrigger className="h-9 bg-background/45">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="updated_at">更新时间</SelectItem>
              <SelectItem value="ai_score">AI 分数</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="w-[110px]">
          <div className="mb-2 text-xs text-muted-foreground">顺序</div>
          <Select value={filters.order} onValueChange={(v) => onOrderChange(v as any)}>
            <SelectTrigger className="h-9 bg-background/45">
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
    </div>
  )
}
