import type { TaskStreamEvent, UnifiedTask } from '@/api/tasks'
import type { ComposeDraft, ComposeReviewResult, FormattedStatus } from './types'

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

export function readString(record: Record<string, unknown>, ...keys: string[]): string {
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'string') return value.trim()
    if (typeof value === 'number') return String(value)
  }
  return ''
}

export function parseComposeDraft(value: unknown): ComposeDraft | null {
  if (!isRecord(value)) return null
  const rawQuestions = Array.isArray(value.questions) ? value.questions : []
  const questions = rawQuestions
    .filter(isRecord)
    .map((item) => ({
      questionId: readString(item, 'questionId', 'question_id'),
      stem: readString(item, 'stem'),
      type: readString(item, 'type', 'questionType', 'question_type'),
      difficulty: readString(item, 'difficulty'),
    }))
    .filter((item) => item.questionId)
  if (questions.length === 0) return null
  return {
    paperName: readString(value, 'paperName', 'paper_name'),
    questions,
  }
}

export function getComposeDraft(task: UnifiedTask | undefined): ComposeDraft | null {
  const rawResult = task?.result
  const result: Record<string, unknown> | null = isRecord(rawResult) ? rawResult : null
  const resultDraft = parseComposeDraft(result?.composeDraft)
  if (resultDraft) return resultDraft

  const events = Array.isArray(task?.events) ? task.events : []
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const rawData = events[index]?.data
    const data: Record<string, unknown> | null = isRecord(rawData) ? rawData : null
    const eventDraft = parseComposeDraft(data?.composeDraft || data?.compose_draft)
    if (eventDraft) return eventDraft
  }
  return null
}

export function getComposeReviewResult(task: UnifiedTask | undefined): ComposeReviewResult | null {
  if (String(task?.task_type || '') !== 'paper_compose') return null
  if (String(task?.status || '').toLowerCase() !== 'completed') return null

  const result = isRecord(task?.result) ? task.result : null
  if (!result) return null

  const paperId = readString(result, 'id', 'paperId', 'paper_id')
  const name = readString(result, 'name', 'paperName', 'paper_name', 'title')
  const rawQuestions = Array.isArray(result.questions) ? result.questions : []
  const questionCount = rawQuestions.length || Number(result.question_count || result.questionCount || 0)

  if (!paperId && !name && !questionCount) return null
  return {
    paperId,
    name: name || '已保存试卷',
    questionCount: Number.isFinite(questionCount) ? Number(questionCount) : 0,
  }
}

export function formatStatus(status: string): FormattedStatus {
  const s = (status || '').toLowerCase()
  if (s === 'running') return { label: '运行中', tone: 'secondary' }
  if (s === 'paused') return { label: '已暂停', tone: 'secondary' }
  if (s === 'pending_review') return { label: '待审核', tone: 'secondary' }
  if (s === 'completed') return { label: '已完成', tone: 'default' }
  if (s === 'failed') return { label: '失败', tone: 'destructive' }
  if (s === 'canceled' || s === 'cancelled') return { label: '已取消', tone: 'destructive' }
  return { label: status || '未知', tone: 'secondary' }
}

export type { TaskStreamEvent }
