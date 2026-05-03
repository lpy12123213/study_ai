import type { TaskStreamEvent } from '@/api/tasks'
import type { TaskStep } from '@/types'

const STAGE_LABELS: Record<string, string> = {
  source_pack: '素材整理',
  reference_crawl: '参考题爬取',
  reference_analysis: '参考题分析',
  brainstorm: '创意发散',
  spec_search: '规格搜索',
  draft_realization: '草稿生成',
  diagram_generation: '配图生成',
  judge: '判题筛选',
  final_selection: '终选入围',
  pending_review: '待审核预览',
}

function toOptionalString(value: unknown): string | undefined {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function toOptionalNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function normalizeStageId(value: string): string {
  const trimmed = String(value || '').trim()
  if (!trimmed) return ''
  return trimmed
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .replace(/[\s-]+/g, '_')
    .toLowerCase()
}

function humanizeStage(stageId: string, stageLabel?: string): string {
  const normalizedId = normalizeStageId(stageId)
  return stageLabel || STAGE_LABELS[normalizedId] || stageId || '进度更新'
}

function buildProgressOutput(data: Record<string, unknown>): unknown {
  const summary = toOptionalString(data.summary)
  const stats = data.stats
  const sample = data.sample
  const output: Record<string, unknown> = {}
  if (summary) output.summary = summary
  if (stats && typeof stats === 'object') Object.assign(output, stats as object)
  if (sample && typeof sample === 'object') output.sample = sample
  return Object.keys(output).length > 0 ? output : undefined
}

function normalizeStreamStep(step: Record<string, unknown>, createdAt?: string): TaskStep | null {
  const id = toOptionalString(step.id)
  if (!id) return null

  const normalized: TaskStep = {
    id,
    title: toOptionalString(step.title) || '步骤',
    status: (toOptionalString(step.status) as TaskStep['status']) || 'completed',
    toolName: toOptionalString(step.toolName),
    input: step.input,
    output: step.output,
    startTime: toOptionalString(step.startTime) || createdAt,
    endTime: toOptionalString(step.endTime),
    error: toOptionalString(step.error),
  }
  return normalized
}

export function taskEventToStep(evt: TaskStreamEvent): TaskStep | null {
  const kind = String(evt.type || '').trim() || 'event'
  const data = evt.data && typeof evt.data === 'object' ? (evt.data as Record<string, unknown>) : {}

  if (kind === 'step' && data.step && typeof data.step === 'object') {
    return normalizeStreamStep(data.step as Record<string, unknown>, evt.created_at)
  }

  if (kind === 'ping') return null

  if (kind === 'progress') {
    const rawStageId =
      toOptionalString(data.stage_id) ||
      toOptionalString(data.stage) ||
      toOptionalString(data.stage_label)
    if (!rawStageId) return null

    const stageId = normalizeStageId(rawStageId)
    const stageLabel = humanizeStage(stageId, toOptionalString(data.stage_label) || toOptionalString(data.stage))
    const progress = toOptionalNumber(data.progress) ?? 0
    const stageGroup = toOptionalString(data.stage_group)
    const stageOrder = toOptionalNumber(data.stage_order)
    const description = toOptionalString(data.description)
    const summary = toOptionalString(data.summary)

    return {
      id: `stage:${stageId}`,
      title: stageLabel,
      status: progress >= 100 ? 'completed' : 'running',
      toolName: 'thinking',
      startTime: evt.created_at,
      input: {
        stage_id: stageId,
        stage_label: stageLabel,
        ...(stageGroup ? { stage_group: stageGroup } : {}),
        ...(stageOrder !== undefined ? { stage_order: stageOrder } : {}),
        ...(description ? { description } : {}),
        ...(summary ? { summary } : {}),
        progress,
      },
      output: buildProgressOutput(data),
    }
  }

  if (kind === 'reasoning_status') {
    const stageLabel =
      toOptionalString(data.stage_label) ||
      humanizeStage(toOptionalString(data.stage_id) || '', toOptionalString(data.stage_label))
    const mode = toOptionalString(data.mode) || 'trace'
    const message = toOptionalString(data.message) || 'reasoning 状态更新'
    return {
      id: `reasoning-status:${evt.seq}`,
      title: `${mode === 'raw' ? '原始 Reason' : '事件 Trace'}: ${message}`,
      status: 'completed',
      toolName: 'reasoning',
      startTime: evt.created_at,
      input: {
        stage_label: stageLabel,
        mode,
      },
      output: data,
    }
  }

  if (kind === 'reasoning_delta') {
    const source = toOptionalString(data.source) || 'trace'
    const content = toOptionalString(data.content) || ''
    const stageId = normalizeStageId(toOptionalString(data.stage_id) || '')
    const stageLabel =
      toOptionalString(data.stage_label) ||
      humanizeStage(stageId, toOptionalString(data.stage_label))
    const prefix = source === 'raw' ? '原始 Reason' : '事件 Trace'
    let title = content ? `${prefix}: ${content}` : prefix
    if (title.length > 240) title = `${title.slice(0, 240)}…`
    return {
      id: `reasoning:${stageId || 'default'}:${source}`,
      title,
      status: 'running',
      toolName: 'reasoning',
      startTime: evt.created_at,
      input: {
        source,
        stage_label: stageLabel,
        _deltaContent: content,
      },
      output: data,
    }
  }

  const content =
    toOptionalString(data.title) ||
    toOptionalString(data.message) ||
    toOptionalString(data.content) ||
    ''

  let title = content ? `${kind}: ${content}` : kind
  if (title.length > 240) title = `${title.slice(0, 240)}…`

  const failed = kind === 'error' || Boolean(data.error)
  return {
    id: `evt-${evt.seq}`,
    title,
    status: failed ? 'failed' : 'completed',
    toolName: kind,
    startTime: evt.created_at,
    error: failed ? String(data.error || data.message || '') : undefined,
  }
}

export function upsertTaskStep(prev: TaskStep[], step: TaskStep): TaskStep[] {
  const index = prev.findIndex((item) => item.id === step.id)
  if (index < 0) return [...prev, step]

  const current = prev[index]
  const merged: TaskStep = {
    ...current,
    ...step,
    input: step.input === undefined ? current.input : step.input,
    output: step.output === undefined ? current.output : step.output,
    error: step.error === undefined ? current.error : step.error,
    startTime: step.startTime || current.startTime,
    endTime: step.endTime || current.endTime,
  }

  return prev.map((item, itemIndex) => (itemIndex === index ? merged : item))
}
