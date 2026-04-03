import type { LessonPlan, Message, ResumableTask, TaskStep } from '@/types'

const MAX_TASK_STEPS = 200
const MAX_STEPS_PER_MESSAGE = 160
const MAX_STEP_CHILDREN = 40
const MAX_STEP_TITLE_CHARS = 4000
const MAX_STEP_INPUT_TEXT_CHARS = 3000
const MAX_STEP_OUTPUT_TEXT_CHARS = 6000
const MAX_THINKING_OUTPUT_TEXT_CHARS = 16000
const MAX_ERROR_CHARS = 2000
const MAX_OBJECT_KEYS = 24
const MAX_ARRAY_ITEMS = 20
const MAX_VALUE_DEPTH = 4
const MAX_PERSISTED_MESSAGE_CONTENT_CHARS = 120000
const MAX_PERSISTED_LESSON_PLAN_CONTENT_CHARS = 12000

function clampMax(value: number, fallback: number): number {
  if (!Number.isFinite(value) || value <= 0) return fallback
  return Math.max(1, Math.floor(value))
}

export function clipTextMiddle(text: string, maxChars: number): string {
  const input = String(text || '')
  const limit = clampMax(maxChars, 1024)
  if (input.length <= limit) return input
  if (limit <= 64) return `${input.slice(0, Math.max(1, limit - 1))}…`
  const budget = Math.max(8, limit - 5)
  const head = Math.max(16, Math.floor(budget * 0.6))
  const tail = Math.max(8, budget - head)
  return `${input.slice(0, head)}\n\n…\n\n${input.slice(-tail)}`
}

export function appendCappedText(prev: string, next: string, maxChars = MAX_THINKING_OUTPUT_TEXT_CHARS): string {
  const incoming = String(next || '')
  if (!incoming) return String(prev || '')
  const combined = prev ? `${prev}\n${incoming}` : incoming
  return clipTextMiddle(combined, maxChars)
}

type SanitizeValueOptions = {
  maxArrayItems?: number
  maxObjectKeys?: number
  maxTextChars?: number
  maxDepth?: number
  depth?: number
  seen?: WeakSet<object>
}

function sanitizeUnknownValue(value: unknown, options: SanitizeValueOptions = {}): unknown {
  if (value === null || value === undefined) return value
  if (typeof value === 'string') return clipTextMiddle(value, clampMax(options.maxTextChars ?? MAX_STEP_OUTPUT_TEXT_CHARS, MAX_STEP_OUTPUT_TEXT_CHARS))
  if (typeof value === 'number' || typeof value === 'boolean') return value

  const maxDepth = clampMax(options.maxDepth ?? MAX_VALUE_DEPTH, MAX_VALUE_DEPTH)
  const depth = typeof options.depth === 'number' && options.depth >= 0 ? Math.floor(options.depth) : 0
  if (depth >= maxDepth) {
    if (Array.isArray(value)) return [`…（共${value.length}项）`]
    if (typeof value === 'object') return { _summary: '对象已截断' }
    return String(value)
  }

  const seen = options.seen ?? new WeakSet<object>()

  if (Array.isArray(value)) {
    const maxArrayItems = clampMax(options.maxArrayItems ?? MAX_ARRAY_ITEMS, MAX_ARRAY_ITEMS)
    const items = value.slice(0, maxArrayItems).map((item) =>
      sanitizeUnknownValue(item, {
        ...options,
        depth: depth + 1,
        seen,
      })
    )
    if (value.length > maxArrayItems) {
      items.push(`…（共${value.length}项）`)
    }
    return items
  }

  if (typeof value === 'object') {
    if (seen.has(value as object)) return '[Circular]'
    seen.add(value as object)
    const maxObjectKeys = clampMax(options.maxObjectKeys ?? MAX_OBJECT_KEYS, MAX_OBJECT_KEYS)
    const entries = Object.entries(value as Record<string, unknown>)
    const next: Record<string, unknown> = {}
    for (const [key, entryValue] of entries.slice(0, maxObjectKeys)) {
      next[key] = sanitizeUnknownValue(entryValue, {
        ...options,
        depth: depth + 1,
        seen,
      })
    }
    if (entries.length > maxObjectKeys) {
      next._truncated = `已截断，原有${entries.length}个字段`
    }
    return next
  }

  return String(value)
}

export function sanitizeTaskStepPatch(patch: Partial<TaskStep>, current?: TaskStep): Partial<TaskStep> {
  const isThinking = patch.toolName === 'thinking' || current?.toolName === 'thinking'
  const next: Partial<TaskStep> = { ...patch }

  if (typeof patch.id === 'string') next.id = clipTextMiddle(patch.id, 200)
  if (typeof patch.title === 'string') next.title = clipTextMiddle(patch.title, MAX_STEP_TITLE_CHARS)
  if (typeof patch.toolName === 'string') next.toolName = clipTextMiddle(patch.toolName, 200)
  if ('input' in patch) {
    next.input = sanitizeUnknownValue(patch.input, {
      maxTextChars: MAX_STEP_INPUT_TEXT_CHARS,
      maxArrayItems: MAX_ARRAY_ITEMS,
      maxObjectKeys: MAX_OBJECT_KEYS,
    })
  }
  if ('output' in patch) {
    next.output = sanitizeUnknownValue(patch.output, {
      maxTextChars: isThinking ? MAX_THINKING_OUTPUT_TEXT_CHARS : MAX_STEP_OUTPUT_TEXT_CHARS,
      maxArrayItems: MAX_ARRAY_ITEMS,
      maxObjectKeys: MAX_OBJECT_KEYS,
    })
  }
  if (typeof patch.error === 'string') next.error = clipTextMiddle(patch.error, MAX_ERROR_CHARS)
  if (Array.isArray(patch.children)) next.children = sanitizeTaskSteps(patch.children, MAX_STEP_CHILDREN)

  return next
}

export function sanitizeTaskStep(step: TaskStep): TaskStep {
  const patch = sanitizeTaskStepPatch(step, step)
  return {
    ...step,
    ...patch,
    id: typeof step.id === 'string' ? clipTextMiddle(step.id, 200) : '',
    title: typeof step.title === 'string' && step.title.trim() ? clipTextMiddle(step.title, MAX_STEP_TITLE_CHARS) : '步骤',
  }
}

export function mergeAndSanitizeTaskStep(current: TaskStep, patch: Partial<TaskStep>): TaskStep {
  return sanitizeTaskStep({
    ...current,
    ...sanitizeTaskStepPatch(patch, current),
  })
}

export function sanitizeTaskSteps(steps: TaskStep[], maxItems = MAX_TASK_STEPS): TaskStep[] {
  if (!Array.isArray(steps) || steps.length === 0) return []
  const limit = clampMax(maxItems, MAX_TASK_STEPS)
  return steps.slice(-limit).map((step) => sanitizeTaskStep(step))
}

export function sanitizeMessageForState(message: Message): Message {
  return {
    ...message,
    steps: Array.isArray(message.steps) ? sanitizeTaskSteps(message.steps, MAX_STEPS_PER_MESSAGE) : message.steps,
  }
}

export function sanitizeMessagesForState(messages: Message[]): Message[] {
  if (!Array.isArray(messages) || messages.length === 0) return []
  return messages.map((message) => sanitizeMessageForState(message))
}

export function sanitizeMessageForPersist(message: Message): Message {
  return {
    ...sanitizeMessageForState(message),
    content: clipTextMiddle(String(message.content || ''), MAX_PERSISTED_MESSAGE_CONTENT_CHARS),
  }
}

export function sanitizeMessagesForPersist(messages: Message[]): Message[] {
  if (!Array.isArray(messages) || messages.length === 0) return []
  return messages.map((message) => sanitizeMessageForPersist(message))
}

export function sanitizeResumableTask(task: ResumableTask): ResumableTask {
  return {
    ...task,
    taskId: clipTextMiddle(String(task.taskId || ''), 200),
    checkpoint: {
      completedSteps: sanitizeTaskSteps(task.checkpoint?.completedSteps || [], MAX_TASK_STEPS),
      pendingSteps: sanitizeTaskSteps(task.checkpoint?.pendingSteps || [], MAX_TASK_STEPS),
      context: sanitizeUnknownValue(task.checkpoint?.context, {
        maxTextChars: MAX_STEP_OUTPUT_TEXT_CHARS,
        maxArrayItems: MAX_ARRAY_ITEMS,
        maxObjectKeys: MAX_OBJECT_KEYS,
      }),
    },
  }
}

export function sanitizeLessonPlan(plan: LessonPlan): LessonPlan {
  return {
    ...plan,
    id: clipTextMiddle(String(plan.id || ''), 200),
    title: clipTextMiddle(String(plan.title || ''), 400),
    subject: clipTextMiddle(String(plan.subject || ''), 200),
    grade: clipTextMiddle(String(plan.grade || ''), 80),
    objectives: Array.isArray(plan.objectives)
      ? plan.objectives.slice(0, MAX_ARRAY_ITEMS).map((item) => clipTextMiddle(String(item || ''), 500))
      : [],
    content:
      typeof plan.content === 'string'
        ? clipTextMiddle(plan.content, MAX_PERSISTED_LESSON_PLAN_CONTENT_CHARS)
        : plan.content,
  }
}
