import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Check,
  X,
  Loader2,
  Clock,
  Pause,
  ChevronRight,
  Globe,
  BookOpen,
  Search,
  Cpu,
  Database,
  FileText,
  User,
  Layers,
  Sparkles,
  Wrench,
} from 'lucide-react'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { StepDetail } from './StepDetail'
import { cn, formatDuration } from '@/lib/utils'
import type { TaskStep as TaskStepType, StepStatus } from '@/types'

interface TaskStepProps {
  step: TaskStepType
  isLast: boolean
}

const statusConfig: Record<
  StepStatus,
  { icon: typeof Check; color: string; bgColor: string }
> = {
  pending: {
    icon: Clock,
    color: 'text-muted-foreground',
    bgColor: 'bg-muted',
  },
  running: {
    icon: Loader2,
    color: 'text-foreground',
    bgColor: 'bg-foreground/10',
  },
  completed: {
    icon: Check,
    color: 'text-foreground',
    bgColor: 'bg-foreground/5',
  },
  failed: {
    icon: X,
    color: 'text-destructive',
    bgColor: 'bg-destructive/10',
  },
  paused: {
    icon: Pause,
    color: 'text-muted-foreground',
    bgColor: 'bg-muted',
  },
}

/** Map tool names to human-readable titles + icons */
const TOOL_DISPLAY: Record<string, { label: string; icon: typeof Globe }> = {
  thinking:                     { label: '思考',               icon: Cpu },
  get_user_profile:              { label: '读取用户画像',       icon: User },
  split_knowledge_points:        { label: '拆分知识点',         icon: Layers },
  review_knowledge_points:       { label: '审核知识点',         icon: Layers },
  web_search_knowledge:          { label: '联网搜索资料',       icon: Globe },
  browse_web_pages:              { label: '浏览网页正文',       icon: Globe },
  wikipedia_search:              { label: '搜索维基百科',       icon: BookOpen },
  mediawiki_search:              { label: '搜索 MediaWiki',     icon: BookOpen },
  stackexchange_search:          { label: '检索 StackExchange', icon: Search },
  github_search:                 { label: '检索 GitHub',        icon: Search },
  search_questions_by_knowledge: { label: '题库检索相关题目',   icon: Search },
  search_questions:              { label: '搜索题目',           icon: Search },
  aggregate_knowledge:           { label: '聚合知识资料',       icon: Database },
  synthesize_sources:            { label: '综合源简报',         icon: Database },
  detect_knowledge_type:         { label: '检测知识类型',       icon: Cpu },
  generate_outline:              { label: '生成写作大纲',       icon: FileText },
  generate_study_material:       { label: '生成自学资料',       icon: Sparkles },
  critique_draft:                { label: '自我批判',           icon: Cpu },
  refine_draft:                  { label: '精炼修订',           icon: FileText },
  generate_diagrams:             { label: '生成教学配图',       icon: Sparkles },
  generate_lesson_plan:         { label: '生成教案',           icon: Sparkles },
  assemble_study_archive:        { label: '组装 Markdown',      icon: FileText },
  revise_markdown:               { label: '修订 Markdown',      icon: FileText },
  save_markdown_file:            { label: '保存 Markdown',      icon: FileText },
  export_study_markdown:         { label: '导出 Markdown',      icon: FileText },
  convert_markdown_to_latex:     { label: 'Markdown → LaTeX',   icon: FileText },
  refine_latex:                  { label: '修订 LaTeX',         icon: FileText },
  compile_latex_to_pdf:          { label: '编译 PDF',           icon: FileText },
  compose_paper:                 { label: '组合试卷',           icon: FileText },
  create_paper:                  { label: '创建试卷',           icon: FileText },
  analyze_paper:                 { label: '分析试卷难度',       icon: Cpu },
  research_knowledge_point:      { label: '研究知识点',         icon: Search },
}

/** Extract the current knowledge-point context from step input */
function extractContext(step: TaskStepType): string | null {
  if (!step.input || typeof step.input !== 'object') return null
  const input = step.input as Record<string, unknown>

  const preferKnowledgePoints = new Set([
    'web_search_knowledge',
    'browse_web_pages',
    'wikipedia_search',
    'mediawiki_search',
    'stackexchange_search',
    'github_search',
    'search_questions_by_knowledge',
    'aggregate_knowledge',
    'synthesize_sources',
    'detect_knowledge_type',
    'generate_outline',
    'generate_study_material',
    'critique_draft',
    'refine_draft',
    'generate_diagrams',
  ])

  const formatKps = (kps: unknown): string | null => {
    if (!Array.isArray(kps)) return null
    const uniq = Array.from(
      new Set(
        kps
          .map((x) => (typeof x === 'string' ? x.trim() : ''))
          .filter((x) => x && x.length < 60)
      )
    )
    if (uniq.length === 0) return null
    if (uniq.length <= 3) return uniq.join('、')
    return `${uniq[0]} 等${uniq.length}个`
  }

  if (step.toolName && preferKnowledgePoints.has(step.toolName)) {
    const kpCtx = formatKps(input.knowledge_points)
    if (kpCtx) return kpCtx
  }

  // Common fields that carry the current topic/knowledge point
  for (const key of ['topic', 'knowledge_point', 'query', 'keyword', 'term']) {
    const val = input[key]
    if (typeof val === 'string' && val.length > 0 && val.length < 80) return val
  }
  return null
}

/** Build a human-readable title for a step */
function getDisplayTitle(step: TaskStepType): { title: string; ToolIcon: typeof Globe | null } {
  // If the step has a tool name, use its mapped label
  if (step.toolName) {
    const display = TOOL_DISPLAY[step.toolName]
    if (display) {
      const ctx = extractContext(step)
      const label = ctx ? `${display.label}：${ctx}` : display.label
      return { title: label, ToolIcon: display.icon }
    }
    // Fallback: strip "调用工具：" prefix and show tool name naturally
    return { title: step.toolName.replace(/_/g, ' '), ToolIcon: Wrench }
  }

  // Non-tool step: strip "调用工具：" if present in the original title
  const raw = (step.title || '').replace(/^调用工具[：:]\s*/i, '').trim()
  return { title: raw || step.title, ToolIcon: null }
}

export function TaskStep({ step, isLast }: TaskStepProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const prevStatusRef = useRef(step.status)
  const config = statusConfig[step.status]
  const StatusIcon = config.icon

  // Calculate duration
  const duration =
    step.startTime && step.endTime
      ? new Date(step.endTime).getTime() - new Date(step.startTime).getTime()
      : null

  const hasDetails =
    (step.input !== undefined && step.input !== null) ||
    (step.output !== undefined && step.output !== null) ||
    !!step.error

  const { title, ToolIcon } = getDisplayTitle(step)

  // Auto-expand thinking while it's running, then auto-collapse once it finishes.
  useEffect(() => {
    const prev = prevStatusRef.current
    prevStatusRef.current = step.status

    if (step.toolName !== 'thinking') return
    if (step.status === 'running') {
      setIsExpanded(true)
      return
    }
    if (prev === 'running') {
      setIsExpanded(false)
    }
  }, [step.status, step.toolName])

  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <div className={cn(isLast ? '' : 'pb-1')}>
        <CollapsibleTrigger asChild>
          <div
            className={cn(
              "group flex items-center gap-2 rounded-md px-2 py-1 cursor-pointer select-none",
              "border border-transparent hover:border-border/60 hover:bg-muted/30",
              step.status === 'failed' && "border-destructive/20 bg-destructive/5 hover:border-destructive/30 hover:bg-destructive/5"
            )}
          >
            <StatusIcon
              className={cn(
                "h-3.5 w-3.5 shrink-0",
                config.color,
                step.status === 'running' && "animate-spin"
              )}
            />

            {ToolIcon && (
              <ToolIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            )}

            <span className="min-w-0 flex-1 truncate text-sm font-medium leading-5">
              {title}
            </span>

            <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground/70">
              {duration !== null ? formatDuration(duration) : step.status === 'running' ? '…' : ''}
            </span>

            {hasDetails && (
              <motion.div
                animate={{ rotate: isExpanded ? 90 : 0 }}
                transition={{ duration: 0.15 }}
                className="shrink-0 text-muted-foreground/50 group-hover:text-muted-foreground"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </motion.div>
            )}
          </div>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <AnimatePresence>
            {isExpanded && hasDetails && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="pl-7 pr-2 pb-2"
              >
                <StepDetail step={step} />
              </motion.div>
            )}
          </AnimatePresence>
        </CollapsibleContent>

        {/* Children steps */}
        {step.children && step.children.length > 0 && (
          <div className="mt-1 ml-3 border-l border-dashed border-border pl-3">
            {step.children.map((child, idx) => (
              <TaskStep
                key={child.id}
                step={child}
                isLast={idx === step.children!.length - 1}
              />
            ))}
          </div>
        )}
      </div>
    </Collapsible>
  )
}
