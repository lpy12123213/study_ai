export function pct(value?: number): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  const normalized = numeric > 1 ? numeric : numeric * 100
  return `${Math.round(normalized)}%`
}

export function sec(value?: number): string {
  const seconds = Number(value)
  if (!Number.isFinite(seconds)) return '--'
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}min`
  return `${Math.round(minutes / 60)}h`
}

export function sumTaskTypes(
  types: Record<string, number> | undefined,
  matches: Array<(taskType: string) => boolean>
): number {
  if (!types) return 0
  return Object.entries(types).reduce((sum, [key, value]) => {
    const normalized = key.toLowerCase()
    return matches.some((match) => match(normalized)) ? sum + Number(value || 0) : sum
  }, 0)
}

export const hasAny = (needles: string[]) => (taskType: string) =>
  needles.some((needle) => taskType.includes(needle))

export const isAiGenerateTask = (taskType: string) =>
  hasAny(['ai_generate', 'question_generate', 'generate_question', 'paper_generate'])(taskType) &&
  !hasAny(['question_library', 'question_evaluate'])(taskType)

export const isStudyMaterialTask = hasAny(['study_material', 'lesson_plan', 'archive'])
export const isQuestionLibraryTask = hasAny(['question_library', 'library_crawl', 'crawl'])

export const timelineStages = [
  { label: '规划', color: 'var(--timeline-thinking)', text: '拆解任务意图与资料边界' },
  { label: '检索', color: 'var(--timeline-grep)', text: '检索题库、试卷与学习档案' },
  { label: '阅读', color: 'var(--timeline-read)', text: '读取候选材料并抽取证据' },
  { label: '生成', color: 'var(--timeline-edit)', text: '生成题目、讲义或视频脚本草稿' },
  { label: '完成', color: 'var(--timeline-done)', text: '输出可复查的结果与导出物' },
] as const
