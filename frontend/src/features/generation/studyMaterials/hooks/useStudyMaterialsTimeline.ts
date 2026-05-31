import { useEffect, useMemo, useState } from 'react'
import { getStudyMaterialsTask, type StudyMaterialsTaskStatus } from '@/api/studyMaterials'
import type { useStickToBottom } from '@/hooks/useStickToBottom'
import { useConversationStore } from '@/stores/useConversationStore'
import { useLessonPlanStore } from '@/stores/useLessonPlanStore'
import { readString } from '@/lib/record'
import { toText } from '@/features/generation/studyMaterials/utils'

type StickToBottom = ReturnType<typeof useStickToBottom>

const EXPORT_FAILURE_TOOLS = ['convert_markdown_to_latex', 'refine_latex', 'compile_latex_to_pdf']

/**
 * Read-model for the study-materials view: conversation selection, derived
 * stream/resume flags, the active message list and the last-task status probe.
 */
export function useStudyMaterialsTimeline({ stick }: { stick: StickToBottom }) {
  const { maybeStick } = stick
  const conversations = useConversationStore((state) => state.conversations)
  const currentConversationId = useConversationStore((state) => state.currentConversationIdByType.study_materials)
  const messagesByConversation = useConversationStore((state) => state.messagesByConversation)
  const lessonPlansById = useLessonPlanStore((state) => state.plansById)

  const activeConversationId = useMemo(() => {
    if (!currentConversationId) return null
    const current = conversations.find((c) => c.id === currentConversationId)
    return current?.type === 'study_materials' ? currentConversationId : null
  }, [conversations, currentConversationId])

  const activeConversation = useMemo(() => {
    if (!activeConversationId) return null
    return conversations.find((c) => c.id === activeConversationId) ?? null
  }, [conversations, activeConversationId])

  const activeStream = activeConversation?.activeStream
  const hasResumableStream = Boolean(activeConversation?.resumable && activeStream?.taskId)
  const lastTask = activeConversation?.lastTask
  const lastTaskErrorTool = toText(lastTask?.materialError?.tool)
  const isLastExportFailure = EXPORT_FAILURE_TOOLS.includes(lastTaskErrorTool)

  const [lastTaskStatus, setLastTaskStatus] = useState<StudyMaterialsTaskStatus | null>(null)
  const [lastTaskStatusError, setLastTaskStatusError] = useState<string | null>(null)

  useEffect(() => {
    const taskId = String(activeConversation?.lastTask?.taskId || '').trim()
    if (!taskId || activeConversation?.status !== 'failed') {
      setLastTaskStatus(null)
      setLastTaskStatusError(null)
      return
    }

    let active = true
    setLastTaskStatusError(null)

    void (async () => {
      try {
        const status = await getStudyMaterialsTask(taskId)
        if (!active) return
        setLastTaskStatus(status)
      } catch (err: unknown) {
        if (!active) return
        setLastTaskStatus(null)
        const message = err instanceof Error ? err.message : readString(err, 'message')
        setLastTaskStatusError(toText(message) || '任务状态获取失败')
      }
    })()

    return () => {
      active = false
    }
  }, [activeConversation?.lastTask?.taskId, activeConversation?.status])

  const messages = useConversationStore((state) => state.getMessages(activeConversationId ?? ''))

  useEffect(() => {
    maybeStick()
  }, [messages, maybeStick])

  return {
    conversations,
    currentConversationId,
    messagesByConversation,
    lessonPlansById,
    activeConversationId,
    activeConversation,
    activeStream,
    hasResumableStream,
    lastTask,
    isLastExportFailure,
    lastTaskStatus,
    lastTaskStatusError,
    messages,
  }
}
