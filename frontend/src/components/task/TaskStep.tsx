import { useState } from 'react'
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
import { cn, formatDuration, formatTime } from '@/lib/utils'
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
  get_user_profile:              { label: '读取用户画像',       icon: User },
  split_knowledge_points:        { label: '拆分知识点',         icon: Layers },
  web_search_knowledge:          { label: '联网搜索资料',       icon: Globe },
  wikipedia_search:              { label: '搜索维基百科',       icon: BookOpen },
  search_questions_by_knowledge: { label: '题库检索相关题目',   icon: Search },
  search_questions:              { label: '搜索题目',           icon: Search },
  aggregate_knowledge:           { label: '聚合知识资料',       icon: Database },
  generate_study_material:       { label: '生成自学资料',       icon: Sparkles },
  compose_paper:                 { label: '组合试卷',           icon: FileText },
  create_paper:                  { label: '创建试卷',           icon: FileText },
  analyze_paper:                 { label: '分析试卷难度',       icon: Cpu },
}

/** Extract the current knowledge-point context from step input */
function extractContext(step: TaskStepType): string | null {
  if (!step.input || typeof step.input !== 'object') return null
  const input = step.input as Record<string, unknown>

  const preferKnowledgePoints = new Set([
    'web_search_knowledge',
    'wikipedia_search',
    'search_questions_by_knowledge',
    'aggregate_knowledge',
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
  const config = statusConfig[step.status]
  const StatusIcon = config.icon

  // Calculate duration
  const duration =
    step.startTime && step.endTime
      ? new Date(step.endTime).getTime() - new Date(step.startTime).getTime()
      : null

  const hasDetails = step.input || step.output || step.error

  const { title, ToolIcon } = getDisplayTitle(step)

  return (
    <Collapsible open={isExpanded} onOpenChange={setIsExpanded}>
      <div className={cn("relative pl-8", isLast ? "pb-0" : "pb-3")}>
        {/* Status indicator */}
        <div
          className={cn(
            "absolute left-0 top-1 h-6 w-6 rounded-full flex items-center justify-center",
            config.bgColor
          )}
        >
          <StatusIcon
            className={cn(
              "h-3.5 w-3.5",
              config.color,
              step.status === 'running' && "animate-spin"
            )}
          />
        </div>

        {/* Content */}
        <CollapsibleTrigger asChild>
          <div
            className={cn(
              "cursor-pointer select-none",
              hasDetails && "hover:opacity-80"
            )}
          >
            <div className="flex items-start gap-1.5">
              {/* Expand icon */}
              {hasDetails && (
                <motion.div
                  animate={{ rotate: isExpanded ? 90 : 0 }}
                  transition={{ duration: 0.15 }}
                  className="mt-0.5 shrink-0"
                >
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50" />
                </motion.div>
              )}

              <div className="flex-1 min-w-0">
                {/* Title with tool icon */}
                <div className="flex items-center gap-1.5 text-sm leading-5">
                  {ToolIcon && (
                    <ToolIcon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  )}
                  <span className="font-medium">{title}</span>
                </div>

                {/* Meta: time + duration */}
                <div className="flex items-center gap-2 mt-0.5 text-[11px] text-muted-foreground/70">
                  {step.startTime && <span>{formatTime(step.startTime)}</span>}
                  {duration !== null && <span>{formatDuration(duration)}</span>}
                </div>

                {/* Error preview when collapsed */}
                {step.error && !isExpanded && (
                  <div className="mt-1 text-xs text-destructive truncate">
                    {step.error}
                  </div>
                )}
              </div>
            </div>
          </div>
        </CollapsibleTrigger>

        {/* Expanded details */}
        <CollapsibleContent>
          <AnimatePresence>
            {isExpanded && hasDetails && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                transition={{ duration: 0.15 }}
                className="ml-5"
              >
                <StepDetail step={step} />
              </motion.div>
            )}
          </AnimatePresence>
        </CollapsibleContent>

        {/* Children steps */}
        {step.children && step.children.length > 0 && (
          <div className="mt-2 ml-4 border-l border-dashed border-border pl-4">
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
