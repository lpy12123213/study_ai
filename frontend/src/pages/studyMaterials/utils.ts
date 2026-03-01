import type { TaskStep } from '@/types'

export function toText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

export function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新自学资料'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}

export function extractMarkdownHref(content: string): string {
  const text = (content || '').trim()
  if (!text) return ''

  // Prefer a line mentioning Markdown (lesson-plan success messages include both Markdown and PDF links).
  const lines = text.split(/\r?\n/)
  for (let i = lines.length - 1; i >= 0; i--) {
    const line = lines[i] || ''
    if (!/Markdown/i.test(line)) continue
    const m = line.match(/\(([^)]+)\)/)
    if (m && m[1]) return m[1].trim()
  }

  // Fallback: grab any Markdown link ending with `.md`.
  const linkRe = /\[[^\]]*]\(([^)]+)\)/g
  let match: RegExpExecArray | null
  while ((match = linkRe.exec(text))) {
    const url = (match[1] || '').trim()
    if (!url) continue
    if (url.toLowerCase().includes('.md')) return url
  }
  return ''
}

export function formatStudyMaterialsError(raw: string): string {
  const msg = (raw || '').trim()
  if (!msg) return '生成失败'

  const lower = msg.toLowerCase()
  if (lower.includes('task not found') || lower.includes('task_not_found')) {
    return '任务已丢失（可能是后端重启或任务过期）。请重新生成。'
  }
  if (lower.includes('event backlog truncated')) {
    return '任务输出过长导致回放被截断。建议重新生成以获得完整输出。'
  }
  if (lower.includes('llm_not_configured')) {
    return '未配置大模型（API Key）。请先配置后端环境变量并重启后端再试。'
  }
  if (lower.includes('llm_request_failed')) {
    return '大模型请求失败。请稍后重试，或检查 Key/模型名/网络/额度。'
  }
  if (lower.includes('markdown_empty')) {
    return '生成内容为空，请换个问题或补充更多要求后再试。'
  }
  if (lower.includes('http error! status: 401') || lower.includes('http error! status: 403')) {
    return '登录已过期或无权限，请重新登录后重试。'
  }

  return msg
}

export function normalizeKnowledgePoints(points: unknown): string[] {
  if (!Array.isArray(points)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const item of points) {
    const text = typeof item === 'string' ? item.trim() : ''
    if (!text) continue
    if (/^(?:\.\.\.|…)(?:\s*(?:[（(]\s*)?共\s*\d+\s*项(?:\s*[)）])?)?\s*$/u.test(text)) {
      continue
    }
    if (seen.has(text)) continue
    seen.add(text)
    out.push(text)
    if (out.length >= 15) break
  }
  return out
}

export function extractStepKnowledgePoints(step: TaskStep): string[] {
  if (step.input && typeof step.input === 'object') {
    const input = step.input as Record<string, unknown>
    const fromInput = normalizeKnowledgePoints(input.knowledge_points)
    if (fromInput.length > 0) return fromInput
  }

  const title = (step.title || '').trim()
  const m = title.match(/当前知识点[：:]\s*([^\r\n]+)/)
  if (m && m[1]) {
    return normalizeKnowledgePoints([m[1].trim()])
  }
  return []
}

