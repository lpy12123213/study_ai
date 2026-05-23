import { useEffect } from 'react'
import * as tasksApi from '@/api/tasks'
import { isRecord, readNumber, readString } from '@/lib/record'
import { useConversationStore } from '@/stores/useConversationStore'

/**
 * Restore the lesson-plan composer input from a previous unified task
 * (e.g. the user clicked "reuse this task" in the task center).
 *
 * The composer is a free-form Chinese prompt; we re-assemble it from the
 * task's structured request fields so the user can tweak and resend.
 */
export function useLessonPlanReuseTask({
  reuseTaskId,
  setInput,
  onConsumed,
}: {
  reuseTaskId: string
  setInput: (next: string) => void
  onConsumed: () => void
}) {
  const setCurrentConversation = useConversationStore((s) => s.setCurrentConversation)

  useEffect(() => {
    if (!reuseTaskId) return

    let active = true
    const run = async () => {
      try {
        const task = await tasksApi.getTask(reuseTaskId)
        if (!active) return
        const req = task?.request
        if (!isRecord(req)) return

        setCurrentConversation(null, 'lesson_plan')

        const subject = readString(req, 'subject').trim()
        const grade = readString(req, 'grade').trim()
        const topic = readString(req, 'topic').trim()
        const duration = readNumber(req, 'duration_minutes', 0)
        const extra = readString(req, 'additional_requirements').trim()

        const parts = [
          [subject, grade, topic ? `《${topic}》` : ''].filter(Boolean).join(' '),
          duration > 0 ? `${duration}分钟` : '',
          '教案',
          extra,
        ].filter(Boolean)

        setInput(parts.join('\n'))
      } finally {
        if (active) onConsumed()
      }
    }
    void run()
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reuseTaskId])
}
