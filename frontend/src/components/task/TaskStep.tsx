import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X,
  Loader2,
  ChevronRight,
  Code2,
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
import { cn } from '@/lib/utils'
import type { TaskStep as TaskStepType } from '@/types'

interface TaskStepProps {
  step: TaskStepType
  isLast: boolean
}

/** Map tool names to human-readable titles + thought */
const TOOL_DISPLAY: Record<string, { label: string; thought?: string; icon: typeof Globe }> = {
  thinking:                     { label: '推理并分析问题',                     thought: '整理思路',             icon: Cpu },
  get_user_profile:              { label: '读取用户画像并获取偏好',             thought: '匹配个性化设置',       icon: User },
  split_knowledge_points:        { label: '拆分并识别核心知识点',               thought: '确定知识范围',         icon: Layers },
  review_knowledge_points:       { label: '审核知识点覆盖及合理性',             thought: '验证知识拆分',         icon: Layers },
  web_search_knowledge:          { label: '联网搜索相关学习资料',               thought: '收集多源信息',         icon: Globe },
  browse_web_pages:              { label: '浏览网页并提取正文内容',             thought: '获取详细资料',         icon: Globe },
  wikipedia_search:              { label: '检索维基百科相关条目',               thought: '补充权威知识',         icon: BookOpen },
  mediawiki_search:              { label: '检索开放知识库及百科内容',           thought: '扩展知识来源',         icon: BookOpen },
  stackexchange_search:          { label: '检索问答社区相关讨论',               thought: '收集实践经验',         icon: Search },
  github_search:                 { label: '检索公开代码及技术资料',             thought: '参考开源方案',         icon: Search },
  search_questions_by_knowledge: { label: '从题库检索关联题目',                 thought: '匹配相关练习',         icon: Search },
  search_questions:              { label: '搜索题目并筛选结果',                 thought: '定位目标题目',         icon: Search },
  aggregate_knowledge:           { label: '聚合多源资料并按知识点整理',         thought: '统一素材结构',         icon: Database },
  synthesize_sources:            { label: '综合多源信息生成简报',               thought: '提炼关键事实',         icon: Database },
  detect_knowledge_type:         { label: '检测知识类型及结构特征',             thought: '判断最佳表达方式',     icon: Cpu },
  generate_outline:              { label: '生成自适应写作大纲',                 thought: '规划内容结构',         icon: FileText },
  generate_study_material:       { label: '生成概念讲解及学习内容',             thought: '撰写核心知识',         icon: Sparkles },
  critique_draft:                { label: '多维度审查并自我批判',               thought: '发现改进空间',         icon: Cpu },
  refine_draft:                  { label: '根据批判意见精炼修订',               thought: '定向优化内容',         icon: FileText },
  generate_diagrams:             { label: '生成教学示意图及配图',               thought: '辅助直观理解',         icon: Sparkles },
  generate_lesson_plan:         { label: '生成完整教案内容',                   thought: '组织教学流程',         icon: Sparkles },
  assemble_study_archive:        { label: '组装结构化学习档案',                 thought: '整理最终文档',         icon: FileText },
  revise_markdown:               { label: '根据审查结果修订文档',               thought: '提升内容质量',         icon: FileText },
  save_markdown_file:            { label: '保存文档到本地文件',                 thought: '持久化存储',           icon: FileText },
  export_study_markdown:         { label: '导出文档并生成下载链接',             thought: '发布可下载文件',       icon: FileText },
  convert_markdown_to_latex:     { label: '读取文档并生成LaTeX/PDF',            thought: '考虑LaTeX排版',       icon: FileText },
  refine_latex:                  { label: '检查并转换DOCX文件及相关内容',       thought: '处理公式图像大小',     icon: FileText },
  compile_latex_to_pdf:          { label: '提取图像尺寸并处理文档格式及渲染',   thought: '编译生成最终PDF',     icon: FileText },
  compose_paper:                 { label: '组合试卷题目及结构',                 thought: '编排题目顺序',         icon: FileText },
  create_paper:                  { label: '创建试卷并初始化配置',               thought: '设置试卷参数',         icon: FileText },
  analyze_paper:                 { label: '分析试卷难度及知识覆盖',             thought: '评估试卷质量',         icon: Cpu },
  research_knowledge_point:      { label: '深入研究知识点细节',                 thought: '获取专业理解',         icon: Search },
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
function getDisplayTitle(step: TaskStepType): { title: string; thought: string | null; ToolIcon: typeof Globe | null } {
  if (step.toolName) {
    const display = TOOL_DISPLAY[step.toolName]
    if (display) {
      if (step.toolName === 'thinking') {
        const raw = (step.title || '').trim()
        const title = raw ? (raw.startsWith('思考') ? raw : `思考：${raw}`) : display.label
        return { title, thought: display.thought || null, ToolIcon: display.icon }
      }
      const ctx = extractContext(step)
      const label = ctx ? `${display.label}：${ctx}` : display.label
      const thought = (step as TaskStepType & { thought?: string }).thought || display.thought || null
      return { title: label, thought, ToolIcon: display.icon }
    }
    return { title: step.toolName.replace(/_/g, ' '), thought: null, ToolIcon: Wrench }
  }

  const raw = (step.title || '').replace(/^调用工具[：:]\s*/i, '').trim()
  return { title: raw || step.title, thought: null, ToolIcon: null }
}

export function TaskStep({ step, isLast }: TaskStepProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const prevStatusRef = useRef(step.status)

  const hasDetails =
    (step.input !== undefined && step.input !== null) ||
    (step.output !== undefined && step.output !== null) ||
    !!step.error

  const { title, thought } = getDisplayTitle(step)

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
      <div className={cn(isLast ? '' : 'pb-1.5')}>
        <CollapsibleTrigger asChild>
          <div
            className={cn(
              "group flex flex-col gap-0.5 rounded-md px-2 py-1.5 cursor-pointer select-none",
              "hover:bg-muted/30",
              step.status === 'failed' && "bg-destructive/5 hover:bg-destructive/5"
            )}
          >
            <div className="flex items-center gap-2">
              {step.status === 'running' ? (
                <Loader2 className="h-3.5 w-3.5 shrink-0 text-foreground animate-spin" />
              ) : step.status === 'failed' ? (
                <X className="h-3.5 w-3.5 shrink-0 text-destructive" />
              ) : (
                <Code2 className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              )}

              <span className="min-w-0 flex-1 truncate text-sm font-medium leading-5">
                {title}
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

            {thought && (
              <span className="pl-[22px] text-xs text-muted-foreground leading-4 truncate">
                {thought}
              </span>
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
