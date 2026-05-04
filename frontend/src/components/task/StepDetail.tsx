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

type RelaxTraceEntry = Record<string, unknown>

function isObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

type WebSearchKnowledgeResult = {
  title?: string
  url?: string
  snippet?: string
  provider?: string
  source_query?: string
}

type WebSearchKnowledgeItem = {
  knowledge_point?: string
  query?: string
  provider?: string
  results: WebSearchKnowledgeResult[]
  summary?: string
  error?: string
  errors?: string[]
}

function toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function toWebSearchKnowledgeItem(raw: unknown): WebSearchKnowledgeItem | null {
  if (!isObject(raw)) return null

  const knowledgePoint = toOptionalString(raw.knowledge_point) || toOptionalString(raw.knowledgePoint)
  const query = toOptionalString(raw.query)
  const provider = toOptionalString(raw.provider)

  const rawResults = Array.isArray(raw.results) ? raw.results : []
  const results: WebSearchKnowledgeResult[] = rawResults
    .filter((r) => isObject(r))
    .map((r) => {
      const title = toOptionalString(r.title) || toOptionalString(r.name) || toOptionalString(r.url) || toOptionalString(r.link)
      const url = toOptionalString(r.url) || toOptionalString(r.link)
      const snippet = toOptionalString(r.snippet) || toOptionalString(r.summary) || toOptionalString(r.text)
      const resultProvider = toOptionalString(r.provider) || provider
      const sourceQuery =
        toOptionalString((r as any).source_query) ||
        toOptionalString((r as any).sourceQuery) ||
        toOptionalString((r as any).source_query_hint) ||
        query

      return {
        title,
        url,
        snippet,
        provider: resultProvider,
        source_query: sourceQuery,
      }
    })
    .filter((r) => Boolean(r.title || r.url))

  const summary = toOptionalString(raw.summary)
  const error = toOptionalString(raw.error)
  const errors = Array.isArray(raw.errors)
    ? raw.errors.map((e) => extractText(e, 1)).filter((e) => Boolean(e))
    : undefined

  if (!knowledgePoint && !query && results.length === 0 && !summary && !error && (!errors || errors.length === 0)) {
    return null
  }

  return {
    knowledge_point: knowledgePoint,
    query,
    provider,
    results,
    summary,
    error,
    errors,
  }
}

function toWebSearchKnowledgeItems(output: unknown): WebSearchKnowledgeItem[] {
  if (!isObject(output)) return []

  if (Array.isArray((output as any).items)) {
    const items: WebSearchKnowledgeItem[] = []
    for (const it of (output as any).items as unknown[]) {
      const parsed = toWebSearchKnowledgeItem(it)
      if (parsed) items.push(parsed)
    }
    return items
  }

  const single = toWebSearchKnowledgeItem(output)
  return single ? [single] : []
}

function renderRelaxTraceEntry(entry: RelaxTraceEntry): string {
  const action = typeof entry.action === 'string' ? entry.action : ''

  if (action === 'initial_select') {
    const selected = Number(entry.selected || entry.selected_total || 0)
    const maxPages = Number(entry.max_pages || entry.maxPages || 0)
    const minQuality = Number(entry.min_quality_score || entry.minQualityScore || 0)
    const dedup = entry.dedup_by_stem === false ? 'false' : 'true'
    return `初始选择：selected=${selected}，max_pages=${maxPages}，min_quality_score=${minQuality}，dedup_by_stem=${dedup}`
  }

  if (action === 'increase_max_pages') {
    const maxPages = Number(entry.max_pages || entry.maxPages || 0)
    const ok = entry.success === undefined ? (entry.fetch_success === false ? false : true) : !!entry.success
    const err = typeof entry.fetch_error === 'string' ? entry.fetch_error : ''
    return `增加翻页上限到 ${maxPages}（success=${ok}${err ? `，error=${err}` : ''}）`
  }

  if (action === 'lower_min_quality_score') {
    const minQuality = Number(entry.min_quality_score || entry.minQualityScore || 0)
    return `降低最小质量分到 ${minQuality}`
  }

  if (action === 'disable_dedup_by_stem') {
    return '关闭按题干去重（dedup_by_stem=false）'
  }

  const summary = extractText(entry, 1)
  return action ? `${action}: ${summary}` : summary
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
  base_url: '资料站点',
  project: 'Wiki项目',
  lang: '语言',
  include_answers: '含答案',
  include_readme: '包含说明文档',
  readme_limit: '说明文档数量',
  readme_max_chars: '说明文档长度上限',
  sort: '排序',
  order: '顺序',
  text_max_length: '文本上限',
  concurrency: '并发数',
  knowledge_points: '知识点',
  top_k: '浏览条数',
  max_chars: '正文上限',
  timeout_s: '超时时间',
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
  knowledge_type: '知识类型',
  parallel_group: '并行组',
  threshold: '阈值',
  should_refine: '需精炼',
  issues: '问题',
  revision_instructions: '修订指令',
  recommended_sections: '推荐小节',
  dimensions: '维度评分',
  relaxTrace: '放宽过程',
}

/** Short human-readable purpose per tool */
const TOOL_PURPOSE: Record<string, string> = {
  split_knowledge_points: '把主题拆成多个可检索的子知识点，便于后续逐点搜集资料与题目。',
  web_search_knowledge: '联网检索每个知识点的资料，补充百科之外的例子、解释与来源链接。',
  browse_web_pages: '浏览关键网页并提取正文摘录，补足搜索摘要的信息不足。',
  wikipedia_search: '从维基百科获取定义/背景摘要，为讲解提供更可靠的基础信息。',
  mediawiki_search: '从开放知识站点检索词条摘要，补充教材式/条目式解释来源。',
  stackexchange_search: '从问答社区检索高质量解释与易错点。',
  github_search: '检索可能有用的公开笔记、教程和讲义，作为进一步阅读补充来源。',
  search_questions_by_knowledge: '按知识点从题库检索例题与练习题，覆盖各子知识点的常见考法。',
  aggregate_knowledge: '将百科、联网搜索、题库结果按知识点聚合，形成结构化素材。',
  synthesize_sources: '将聚合素材去噪、提炼关键事实，生成结构化“源简报”，减轻后续写作上下文负担。',
  detect_knowledge_type: '判断知识点类型（定义/定理/算法等），用于自适应大纲与写作重点。',
  generate_outline: '基于知识类型与源简报生成写作大纲，并给出每节的验证标准。',
  generate_study_material: '基于聚合素材生成“讲解 + 例题分步解答 + 练习题”。',
  critique_draft: '对草稿进行多维度自我审查（准确性/清晰度/完整性/原创性/深度匹配），输出可执行的修订指令。',
  refine_draft: '根据自我批判的修订指令做定向精炼（高分草稿可自动跳过）。',
  generate_diagrams: '为知识点生成教学配图，用于增强直观理解（与批判阶段可并行）。',
  assemble_study_archive: '把各知识点内容整理成最终自学档案。',
  save_markdown_file: '将生成的文档保存到本地文件，便于下载与复用。',
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

  // Special: thinking stream should show full text (not truncated previews).
  if (step.toolName === 'thinking') {
    const text = typeof step.output === 'string' ? step.output : extractText(step.output, 0)
    return (
      <div className="mt-2 space-y-2 text-xs">
        {text && (
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-2 text-foreground/80 leading-5">
            {text}
          </pre>
        )}
        {hasError && (
          <div className="text-destructive bg-destructive/10 rounded-md px-2 py-1.5">
            {step.error}
          </div>
        )}
      </div>
    )
  }

  if (step.toolName === 'web_search_knowledge') {
    const items = toWebSearchKnowledgeItems(step.output)
    if (items.length > 0) {
      const inputEntries = hasInput ? flattenToEntries(step.input) : []
      return (
        <div className="mt-2 pt-2 border-t border-border/50 space-y-3 text-xs">
          {purpose && (
            <div>
              <div className="text-muted-foreground/60 mb-1 font-medium uppercase tracking-wider text-[10px]">
                用意
              </div>
              <div className="text-foreground/80 leading-5">{purpose}</div>
            </div>
          )}

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

          <div>
            <div className="text-muted-foreground/60 mb-1 font-medium uppercase tracking-wider text-[10px]">
              结果链接
            </div>
            <div className="space-y-4">
              {items.map((item, idx) => {
                const header = item.knowledge_point || item.query || `#${idx + 1}`
                const results = item.results || []
                const shown = results.slice(0, 8)

                return (
                  <div key={`${header}:${idx}`} className="space-y-2">
                    <div className="text-foreground/90 font-medium">{header}</div>

                    {shown.length > 0 ? (
                      <div className="space-y-2">
                        {shown.map((r, i) => {
                          const title = r.title || r.url || `#${i + 1}`
                          const metaParts = [r.source_query].filter(Boolean)
                          const meta = metaParts.length > 0 ? metaParts.join(' · ') : ''

                          const body = (
                            <div className="rounded-md border border-border/60 bg-background/40 hover:bg-muted/40 transition-colors p-2">
                              <div className="text-foreground/90 font-medium leading-5">{title}</div>
                              {r.url && <div className="text-[10px] text-muted-foreground break-all mt-0.5">{r.url}</div>}
                              {r.snippet && <div className="text-foreground/80 leading-5 mt-1">{r.snippet}</div>}
                              {meta && <div className="text-[10px] text-muted-foreground mt-1">{meta}</div>}
                            </div>
                          )

                          return r.url ? (
                            <a
                              key={i}
                              href={r.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="block"
                            >
                              {body}
                            </a>
                          ) : (
                            <div key={i}>{body}</div>
                          )
                        })}
                        {results.length > shown.length && (
                          <div className="text-muted-foreground/70 text-[11px]">
                            仅展示前 {shown.length} 条（共 {results.length} 条）
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-muted-foreground/70">未返回可用搜索结果</div>
                    )}

                    {(item.summary || item.error || (item.errors && item.errors.length > 0)) && (
                      <details className="rounded-md border border-border/40 bg-background/40">
                        <summary className="cursor-pointer px-2 py-1.5 text-[11px] text-muted-foreground/70 select-none">
                          查看摘要/错误
                        </summary>
                        <div className="space-y-2 p-2 text-foreground/80">
                          {item.summary && (
                            <pre className="whitespace-pre-wrap leading-5 bg-muted/30 rounded-md p-2">
                              {item.summary}
                            </pre>
                          )}
                          {item.error && (
                            <div className="text-destructive bg-destructive/10 rounded-md px-2 py-1.5">
                              {item.error}
                            </div>
                          )}
                          {item.errors && item.errors.length > 0 && (
                            <div className="text-muted-foreground/80 whitespace-pre-wrap">
                              {item.errors.slice(0, 6).map((e, i) => (
                                <div key={i}>{e}</div>
                              ))}
                              {item.errors.length > 6 && (
                                <div className="text-muted-foreground/70 pt-1">
                                  仅展示前 6 条（共 {item.errors.length} 条）
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      </details>
                    )}
                  </div>
                )
              })}
            </div>
          </div>

          {hasError && (
            <div className="text-destructive bg-destructive/10 rounded-md px-2 py-1.5">
              {step.error}
            </div>
          )}

          {(hasInput || hasOutput) && (
            <details className="rounded-md border border-border/40 bg-background/40">
              <summary className="cursor-pointer px-2 py-1.5 text-[11px] text-muted-foreground/70 select-none">
                查看原始数据（JSON）
              </summary>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] text-foreground/80 leading-5">
                {(() => {
                  try {
                    return JSON.stringify({ input: step.input, output: step.output }, null, 2)
                  } catch {
                    return '(无法序列化)'
                  }
                })()}
              </pre>
            </details>
          )}
        </div>
      )
    }
  }

  const inputEntries = hasInput ? flattenToEntries(step.input) : []
  const outputEntries = hasOutput ? flattenToEntries(step.output) : []
  const relaxTrace =
    isObject(step.output) && Array.isArray((step.output as any).relaxTrace)
      ? (((step.output as any).relaxTrace as unknown[]) || []).filter((x) => isObject(x)) as RelaxTraceEntry[]
      : []

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
      {relaxTrace.length > 0 && (
        <div>
          <div className="text-muted-foreground/60 mb-1 font-medium uppercase tracking-wider text-[10px]">
            放宽过程
          </div>
          <div className="space-y-1 text-foreground/80 bg-muted/30 rounded-md p-2">
            {relaxTrace.slice(0, 24).map((it, idx) => (
              <div key={idx} className="break-all whitespace-pre-wrap">
                {renderRelaxTraceEntry(it)}
              </div>
            ))}
            {relaxTrace.length > 24 && (
              <div className="text-muted-foreground/70 pt-1">
                仅展示前 24 条（共 {relaxTrace.length} 条）
              </div>
            )}
          </div>
        </div>
      )}

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

      {/* Raw payload */}
      {(hasInput || hasOutput) && (
        <details className="rounded-md border border-border/40 bg-background/40">
          <summary className="cursor-pointer px-2 py-1.5 text-[11px] text-muted-foreground/70 select-none">
            查看原始数据（JSON）
          </summary>
          <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words p-2 text-[11px] text-foreground/80 leading-5">
            {(() => {
              try {
                return JSON.stringify({ input: step.input, output: step.output }, null, 2)
              } catch {
                return '(无法序列化)'
              }
            })()}
          </pre>
        </details>
      )}
    </div>
  )
}
