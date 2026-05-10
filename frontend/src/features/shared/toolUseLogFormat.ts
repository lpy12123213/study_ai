import type { TaskStep } from '@/types'

export type ToolLogBucket = 'read' | 'search' | 'thought' | 'action'

export type ToolLogRow = {
  id: string
  bucket: ToolLogBucket
  verb: string
  detail: string
  status: TaskStep['status']
  /** 搜索分组用：题库 / Tavily / 其他 provider */
  searchBrand?: string
}

/** 连续条目合并分组（不包含 thought）。 */
export type ToolLogBundledRow = {
  rows: ToolLogRow[]
}

function asRecord(input: unknown): Record<string, unknown> | null {
  if (input && typeof input === 'object' && !Array.isArray(input)) {
    return input as Record<string, unknown>
  }
  return null
}

function strVal(v: unknown): string {
  if (typeof v === 'string') return v.trim()
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return ''
}

function pickInputString(input: unknown, keys: string[]): string {
  const o = asRecord(input)
  if (!o) return ''
  for (const k of keys) {
    const s = strVal(o[k])
    if (s) return s
  }
  return ''
}

function basename(path: string): string {
  const p = path.replace(/\\/g, '/').replace(/\/+$/, '')
  const idx = p.lastIndexOf('/')
  return idx >= 0 ? p.slice(idx + 1) : p
}

function lineRangeFromStep(step: TaskStep): string | null {
  const out = asRecord(step.output)
  if (out) {
    const start = out.start_line ?? out.startLine ?? out.line_start ?? out.offset
    const end = out.end_line ?? out.endLine ?? out.line_end
    if (typeof start === 'number' && typeof end === 'number') {
      return `L${start}-${end}`
    }
    if (typeof start === 'number') {
      return `L${start}`
    }
  }
  const inp = asRecord(step.input)
  if (inp) {
    const off = inp.offset
    const lim = inp.limit
    if (typeof off === 'number' && typeof lim === 'number' && lim > 0) {
      return `L${off + 1}-${off + lim}`
    }
  }
  return null
}

function shortArgSummary(input: unknown): string {
  const o = asRecord(input)
  if (!o) return ''
  for (const k of ['paper_name', 'keyword', 'requirement', 'topic', 'name']) {
    const s = strVal(o[k])
    if (s && s.length < 100) return s
  }
  return ''
}

function pickProvider(step: TaskStep): string {
  for (const source of [step.output, step.input]) {
    const o = asRecord(source)
    if (!o) continue
    const p = strVal(o.provider)
    if (p) return p.toLowerCase()
    const nested = asRecord(o.items)
    if (nested) {
      const p2 = strVal(nested.provider)
      if (p2) return p2.toLowerCase()
    }
  }
  return ''
}

function capitalizeBrand(raw: string): string {
  const s = raw.trim()
  if (!s) return ''
  if (/^tavily$/i.test(s)) return 'Tavily'
  if (/^exa$/i.test(s)) return 'Exa'
  if (/^bigmodel$/i.test(s)) return 'BigModel'
  if (/^metaso$/i.test(s)) return 'Metaso'
  return s.slice(0, 1).toUpperCase() + s.slice(1).toLowerCase()
}

/** 题库检索类（非联网 Tavily）。 */
function isQuestionBankSearch(name: string): boolean {
  return (
    name.includes('search_questions') ||
    name === 'compose_paper_blueprint' ||
    name === 'batch_get_question_details' ||
    name === 'get_available_filters'
  )
}

/** 面向公网/MCP、默认走 Tavily 的检索。 */
function isWebFacingSearchTool(name: string): boolean {
  if (name.includes('grep') || name.includes('glob') || name.includes('find_file')) return false
  if (name.includes('codebase')) return false

  const webHints = ['web_search', 'browse_web', 'wikipedia', 'mediawiki', 'stackexchange', 'github_search']
  if (webHints.some((h) => name.includes(h))) return true

  if (name === 'web_search' || name.endsWith('_web_search')) return true

  return false
}

export function classifyToolStep(step: TaskStep): ToolLogBucket {
  const name = (step.toolName || '').toLowerCase()
  if (name === 'thinking') return 'thought'

  const title = (step.title || '').trim()
  if (!name && title.includes('思考')) return 'thought'

  const searchNeedles = ['search', 'grep', 'glob', 'lookup', 'find_file', 'codebase']
  if (searchNeedles.some((n) => name.includes(n))) return 'search'

  const readNeedles = ['read_file', 'get_question_detail', 'get_papers', 'get_paper', 'load_file', 'fetch_file']
  if (name.startsWith('read_')) return 'read'
  if (readNeedles.some((n) => name.includes(n))) return 'read'

  return 'action'
}

/** 搜索行展示的 provider 标签（联网默认 Tavily）。 */
export function resolveSearchBrand(toolNameLower: string, step: TaskStep): string {
  const name = toolNameLower
  if (isQuestionBankSearch(name)) return '题库'

  const fromApi = capitalizeBrand(pickProvider(step))
  if (fromApi) return fromApi

  if (isWebFacingSearchTool(name)) return 'Tavily'

  if (classifyToolStep(step) !== 'search') return ''

  return ''
}

/** One log line plus metadata for summaries and grouping. */
export function formatToolLogRow(step: TaskStep): ToolLogRow {
  const bucket = classifyToolStep(step)
  const name = (step.toolName || '').toLowerCase()
  const displayToolName = step.toolName || ''
  const input = step.input

  if (bucket === 'thought') {
    const raw = (step.title || '').replace(/^思考[：:]\s*/i, '').trim()
    const t = raw || '…'
    const short = t.length > 160 ? `${t.slice(0, 157)}…` : t
    return { id: step.id, bucket, verb: '思考', detail: short, status: step.status }
  }

  if (bucket === 'read') {
    const path =
      pickInputString(input, ['path', 'file_path', 'target_file', 'filepath', 'file', 'question_id']) ||
      pickInputString(input, ['paper_id'])
    const displayRaw = path || displayToolName || 'resource'
    const display = path ? basename(displayRaw) || displayRaw : displayRaw
    const range = lineRangeFromStep(step)
    const suffix = range ? ` ${range}` : ''
    return { id: step.id, bucket, verb: '读取', detail: `${display}${suffix}`, status: step.status }
  }

  if (bucket === 'search') {
    const brand = resolveSearchBrand(name, step)
    const pattern =
      pickInputString(input, ['glob_pattern', 'pattern', 'glob', 'keyword', 'query', 'term', 'q']) || ''
    const dir =
      pickInputString(input, ['target_directory', 'directory', 'dir', 'subject', 'edu_level', 'repo', 'root']) ||
      'workspace'
    const pat = pattern || '*'

    let detail = ''
    if (pattern && !name.includes('grep') && !name.includes('glob') && !name.includes('find_file')) {
      detail = `「${pattern}」· ${dir}`
    } else if (pattern) {
      detail = `files ${pat} in ${dir}`
    } else {
      detail = `${displayToolName || 'tool'} in ${dir}`
    }

    return {
      id: step.id,
      bucket,
      verb: brand ? `搜索 (${brand})` : '搜索',
      detail,
      status: step.status,
      searchBrand: brand || undefined,
    }
  }

  const argHint = shortArgSummary(input)
  const strippedTitle = (step.title || '').replace(/^调用工具[：:]\s*/i, '').trim()
  const base = displayToolName || strippedTitle || 'tool'
  const detail = argHint ? `${base} — ${argHint}` : base
  return { id: step.id, bucket, verb: '调用', detail, status: step.status }
}

export interface ToolLogSummary {
  reads: number
  searches: number
  others: number
  searchBrand?: string
}

/** 计算结构化摘要数据（用于等宽展示）。 */
export function calcToolLogSummary(rows: ToolLogRow[]): ToolLogSummary {
  const reads = rows.filter((r) => r.bucket === 'read').length
  const searches = rows.filter((r) => r.bucket === 'search').length
  const searchRows = rows.filter((r) => r.bucket === 'search')
  const allSearchAreTavily =
    searchRows.length > 0 && searchRows.every((r) => r.searchBrand === 'Tavily')
  const thoughts = rows.filter((r) => r.bucket === 'thought').length
  const actions = rows.filter((r) => r.bucket === 'action').length

  return {
    reads,
    searches,
    others: thoughts + actions,
    searchBrand: allSearchAreTavily ? 'Tavily' : undefined,
  }
}

/** 外层折叠条的摘要文案（不出现 Explored）。 */
export function buildToolLogSummary(rows: ToolLogRow[]): string {
  const summary = calcToolLogSummary(rows)
  const { reads, searches, others, searchBrand } = summary

  if (rows.length === 0) return '工具'

  const parts: string[] = []
  if (reads > 0) parts.push(`${reads} 次读取`)
  if (searches > 0) {
    parts.push(searchBrand ? `${searches} 次搜索 · ${searchBrand}` : `${searches} 次搜索`)
  }

  if (others > 0) {
    if (parts.length === 0) parts.push(`${others} 步`)
    else parts.push(`${others} 其它`)
  } else if (parts.length === 0) {
    parts.push(`${rows.length} 步`)
  }

  return parts.join(' · ')
}

function mergeableTail(a: ToolLogRow, b: ToolLogRow): boolean {
  if (a.bucket !== b.bucket) return false
  if (a.bucket === 'thought') return false
  if (a.bucket === 'search') return (a.searchBrand || '') === (b.searchBrand || '')
  return true
}

/** 合并「连续同类」工具行以便组内折叠。 */
export function bundleConsecutiveToolRows(rows: ToolLogRow[]): ToolLogBundledRow[] {
  if (rows.length === 0) return []
  const out: ToolLogBundledRow[] = []
  let buf: ToolLogRow[] = [rows[0]!]

  for (let i = 1; i < rows.length; i++) {
    const prev = rows[i - 1]!
    const cur = rows[i]!
    if (mergeableTail(prev, cur)) {
      buf.push(cur)
      continue
    }
    out.push({ rows: buf })
    buf = [cur]
  }
  out.push({ rows: buf })
  return out
}
