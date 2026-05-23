import type { Subject } from '@/types'

const grades = [
  '一年级',
  '二年级',
  '三年级',
  '四年级',
  '五年级',
  '六年级',
  '七年级',
  '八年级',
  '九年级',
  '高一',
  '高二',
  '高三',
]

export function toText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function stripAll(haystack: string, needle: string): string {
  if (!needle) return haystack
  let result = haystack
  while (result.includes(needle)) result = result.replace(needle, '')
  return result
}

function getStageByGrade(grade: string | null): '小学' | '初中' | '高中' | '' {
  if (!grade) return ''
  const g = grade.trim()
  if (/^[一二三四五六]年级/.test(g)) return '小学'
  if (/^[七八九]年级/.test(g)) return '初中'
  if (/^高[一二三]/.test(g)) return '高中'
  return ''
}

export function extractGradeFromText(text: string): string | null {
  const t = (text || '').trim()
  for (const g of grades) {
    if (t.includes(g)) return g
  }
  const m = t.match(/(小学|初中|高中|初一|初二|初三)/)
  if (m) {
    const map: Record<string, string> = {
      初一: '七年级',
      初二: '八年级',
      初三: '九年级',
    }
    return map[m[1]] || null
  }
  return null
}

export function extractDurationMinutesFromText(text: string): number | null {
  const m = (text || '').match(/(\d{2,3})\s*(分钟|min)/i)
  if (!m) return null
  const n = parseInt(m[1], 10)
  return n >= 15 && n <= 180 ? n : null
}

export function extractSubjectFromText(
  text: string,
  subjects: Subject[] | undefined,
  grade: string | null
): string | null {
  const list = subjects ?? []
  const t = text || ''

  const direct = list
    .map((s) => s?.name)
    .filter((name): name is string => typeof name === 'string' && !!name)
    .filter((name) => t.includes(name))
    .sort((a, b) => b.length - a.length)[0]
  if (direct) return direct

  const stage = getStageByGrade(grade)
  const stageOrder = stage ? [stage, '高中', '初中', '小学'] : ['高中', '初中', '小学']

  const aliasKeys = [
    '语文',
    '数学',
    '英语',
    '物理',
    '化学',
    '生物',
    '政治',
    '历史',
    '地理',
    '道德与法治',
    '科学',
  ]

  const alias = aliasKeys.find((k) => t.includes(k))
  if (!alias) return null

  const candidates = stageOrder.map((s) => `${s}${alias}`)
  for (const c of candidates) {
    if (list.some((x) => x?.name === c)) return c
  }

  const fuzzy = list
    .map((s) => s?.name)
    .filter((name): name is string => typeof name === 'string')
    .find((name) => name.includes(alias))
  return fuzzy ?? null
}

export function extractTopicFromText(text: string, subject: string | null, grade: string | null): string {
  const raw = (text || '').trim()
  if (!raw) return ''

  const book = raw.match(/《([^》]{2,80})》/)?.[1]?.trim()
  if (book) return book

  const byKey = raw.match(/(?:课题|主题|标题|topic)\s*[:：]\s*(.+)/i)?.[1]
  if (byKey) return byKey.split('\n')[0].trim()

  let t = raw
  if (subject) t = stripAll(t, subject)
  if (grade) t = stripAll(t, grade)
  t = t.replace(/\d{1,3}\s*(分钟|min)/gi, '')
  t = t
    .replace(/[，。；、,.!！?？]/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/(帮我|请|生成|写|做|来一份|一份|一个|教案|教学|设计|详细|完整版|课程|课时)/g, '')
    .trim()

  if (!t) return ''
  return t.length > 40 ? t.slice(0, 40).trim() : t
}

export function toConversationTitle(text: string): string {
  const t = (text || '').trim()
  if (!t) return '新教案'
  return t.length > 18 ? `${t.slice(0, 18)}…` : t
}
