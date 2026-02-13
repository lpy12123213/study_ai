import type { TaskStep } from '@/types'

interface StepDetailProps {
  step: TaskStep
}

/**
 * Recursively flatten an unknown value into displayable text.
 * For deeply nested data, recursively extract string content up to a depth limit.
 */
function extractText(data: unknown, depth = 0): string {
  if (data === null || data === undefined) return ''
  if (typeof data === 'string') return data
  if (typeof data === 'number' || typeof data === 'boolean') return String(data)
  if (depth > 3) return '…'
  if (Array.isArray(data)) {
    if (data.length === 0) return '(空)'
    if (data.every((v) => typeof v === 'string' || typeof v === 'number')) {
      return data.join('、')
    }
    return data.map((v) => extractText(v, depth + 1)).filter(Boolean).join('\n')
  }
  if (typeof data === 'object') {
    const parts: string[] = []
    for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
      if (value === null || value === undefined) continue
      const text = extractText(value, depth + 1)
      if (text) parts.push(`${key}: ${text}`)
    }
    return parts.join('\n')
  }
  return ''
}

/** Flatten data into key-value pairs, with richer value extraction */
function flattenToEntries(data: unknown): [string, string][] {
  if (data === null || data === undefined) return []
  if (typeof data === 'string') {
    if (data.length === 0) return []
    return [['', data.length > 300 ? data.slice(0, 300) + '…' : data]]
  }
  if (typeof data === 'number' || typeof data === 'boolean') return [['', String(data)]]
  if (Array.isArray(data)) {
    if (data.length === 0) return []
    if (data.every((v) => typeof v === 'string' || typeof v === 'number')) {
      return [['', data.join('、')]]
    }
    // For arrays of objects, extract summaries
    const summaries = data.slice(0, 5).map((item) => {
      const text = extractText(item, 1)
      return text.length > 150 ? text.slice(0, 150) + '…' : text
    })
    const entries: [string, string][] = summaries.map((s, i) => [`#${i + 1}`, s])
    return entries
  }
  if (typeof data === 'object') {
    const entries: [string, string][] = []
    for (const [key, value] of Object.entries(data as Record<string, unknown>)) {
      if (value === null || value === undefined) continue
      const text = extractText(value, 1)
      if (!text) continue
      const display = text.length > 300 ? text.slice(0, 300) + '…' : text
      entries.push([key, display])
    }
    return entries
  }
  return []
}

/** Nice labels for common keys */
const KEY_LABELS: Record<string, string> = {
  topic: '主题',
  subject: '学科',
  query: '查询',
  query_hint: '检索提示',
  keyword: '关键词',
  term: '术语',
  limit: '数量上限',
  site: '站点',
  base_url: '站点URL',
  project: 'Wiki项目',
  lang: '语言',
  include_answers: '含答案',
  include_readme: '含README',
  readme_limit: 'README数',
  readme_max_chars: 'README上限',
  sort: '排序',
  order: '顺序',
  text_max_length: '文本上限',
  concurrency: '并发数',
  knowledge_points: '知识点',
  top_k: '浏览条数',
  max_chars: '正文上限',
  timeout_s: '超时秒数',
  content: '内容',
  summary: '摘要',
  result: '结果',
  results: '结果',
  questions: '题目',
  count: '数量',
  title: '标题',
  description: '描述',
  markdown: '正文',
  text: '文本',
  url: '链接',
  source: '来源',
  difficulty: '难度',
  score: '分数',
}

/** Short human-readable purpose per tool */
const TOOL_PURPOSE: Record<string, string> = {
  split_knowledge_points: '把主题拆成多个可检索的子知识点，便于后续逐点搜集资料与题目。',
  web_search_knowledge: '联网检索每个知识点的资料，补充百科之外的例子、解释与来源链接。',
  browse_web_pages: '浏览关键网页并提取正文摘录，补足搜索摘要的信息不足。',
  wikipedia_search: '从维基百科获取定义/背景摘要，为讲解提供更可靠的基础信息。',
  mediawiki_search: '从 MediaWiki 站点（如 Wikibooks/ProofWiki 等）检索词条摘要，补充教材式/条目式解释来源。',
  stackexchange_search: '从 StackExchange 网络检索高质量问答解释与易错点（通常有高票答案）。',
  github_search: '在 GitHub 上检索可能有用的笔记/教程/讲义仓库，作为进一步阅读补充来源。',
  search_questions_by_knowledge: '按知识点从题库检索例题与练习题，覆盖各子知识点的常见考法。',
  aggregate_knowledge: '将百科、联网搜索、题库结果按知识点聚合，形成结构化素材。',
  generate_study_material: '基于聚合素材生成“讲解 + 例题分步解答 + 练习题”。',
  assemble_study_archive: '把各知识点内容整理成最终的 Markdown 自学档案。',
  save_markdown_file: '将生成的 Markdown 保存到本地文件，便于下载与复用。',
  review_content: '对生成内容做自检与审查，发现问题则进入迭代修正。',
}

function displayKey(key: string): string {
  if (!key) return ''
  return KEY_LABELS[key] || key
}

export function StepDetail({ step }: StepDetailProps) {
  const hasInput = step.input !== undefined && step.input !== null
  const hasOutput = step.output !== undefined && step.output !== null
  const hasError = !!step.error
  const purpose = step.toolName ? TOOL_PURPOSE[step.toolName] : ''

  if (!hasInput && !hasOutput && !hasError) {
    return null
  }

  const inputEntries = hasInput ? flattenToEntries(step.input) : []
  const outputEntries = hasOutput ? flattenToEntries(step.output) : []

  return (
    <div className="mt-2 pt-2 border-t border-border/50 space-y-3 text-xs">
      {/* Purpose */}
      {purpose && (
        <div>
          <div className="text-muted-foreground/60 mb-1 font-medium uppercase tracking-wider text-[10px]">
            用意
          </div>
          <div className="text-foreground/80 leading-5">{purpose}</div>
        </div>
      )}

      {/* Input */}
      {inputEntries.length > 0 && (
        <div>
          <div className="text-muted-foreground/60 mb-1 font-medium uppercase tracking-wider text-[10px]">输入</div>
          <div className="space-y-1 text-foreground/80">
            {inputEntries.map(([key, value], i) => (
              <div key={i} className={key ? "flex gap-2" : ""}>
                {key && <span className="text-muted-foreground shrink-0">{displayKey(key)}</span>}
                <span className="break-all whitespace-pre-wrap">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Output */}
      {outputEntries.length > 0 && (
        <div>
          <div className="text-muted-foreground/60 mb-1 font-medium uppercase tracking-wider text-[10px]">返回</div>
          <div className="space-y-1 text-foreground/80 bg-muted/30 rounded-md p-2">
            {outputEntries.map(([key, value], i) => (
              <div key={i} className={key ? "flex gap-2" : ""}>
                {key && <span className="text-muted-foreground shrink-0">{displayKey(key)}</span>}
                <span className="break-all whitespace-pre-wrap">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {hasError && (
        <div className="text-destructive bg-destructive/10 rounded-md px-2 py-1.5">
          {step.error}
        </div>
      )}
    </div>
  )
}
