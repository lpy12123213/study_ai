import { useCallback, useEffect, useRef, useState } from 'react'

import {
  confirmQuestionLibrarySessionQuestion,
  discardQuestionLibraryPreview,
  regenerateQuestionLibrarySection,
} from '@/api/questionLibrary'
import type { AiGenerateStudioSession } from '@/features/aiGenerate/types'
import {
  applyRegeneratedDraftSection,
  failDraftSectionRegeneration,
  finalizeDraftSectionRegeneration,
  markDraftSectionRegenerating,
  toggleDraftSectionLock,
  updateDraftSection,
} from '@/features/aiGenerate/useAiGenerateSession'

type ToastStatus = 'completed' | 'failed'

interface ToastPayload {
  id: string
  title: string
  status: ToastStatus
}

interface QuestionLibraryLike {
  refreshList: () => Promise<void>
}

interface QuestionLibraryTasksLike {
  clearDraftPreview: () => void
}

interface UseDraftActionsOptions {
  session: AiGenerateStudioSession | null
  setSession: React.Dispatch<React.SetStateAction<AiGenerateStudioSession | null>>
  setSearchParams: (params: Record<string, string>) => void
  lib: QuestionLibraryLike
  tasks: QuestionLibraryTasksLike
  pushToast: (toast: ToastPayload) => void
  syncSessionFromServer: (sessionId: string) => Promise<AiGenerateStudioSession | null>
  onDisableAutoAppend: () => void
}

export function useDraftActions(options: UseDraftActionsOptions) {
  const [isDiscarding, setIsDiscarding] = useState(false)

  const draftRefs = useRef<Array<HTMLDivElement | null>>([])
  const regenerateControllersRef = useRef<Record<string, AbortController>>({})

  useEffect(() => {
    return () => {
      Object.values(regenerateControllersRef.current).forEach((controller) => controller.abort())
      regenerateControllersRef.current = {}
    }
  }, [])

  const handleSectionChange = useCallback(
    (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis', content: string) => {
      options.setSession((prev) => (prev ? updateDraftSection(prev, questionId, sectionKey, content) : prev))
    },
    [options.setSession]
  )

  const handleToggleSectionLock = useCallback(
    (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis') => {
      options.setSession((prev) => (prev ? toggleDraftSectionLock(prev, questionId, sectionKey) : prev))
    },
    [options.setSession]
  )

  const handleRegenerateSection = useCallback(
    (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis') => {
      const activeSession = options.session
      if (!activeSession?.previewId) {
        options.pushToast({ id: 'ai-generate-regenerate-missing-preview', title: '请等待草稿生成完成后再重生成片段', status: 'failed' })
        return
      }

      const targetDraft = activeSession.drafts.find((draft) => draft.questionId === questionId)
      if (!targetDraft) return
      if (targetDraft.sections[sectionKey].locked) {
        options.pushToast({ id: `ai-generate-locked-${questionId}-${sectionKey}`, title: '该片段已锁定，请先解锁后再重生成', status: 'failed' })
        return
      }

      const requestKey = `${questionId}:${sectionKey}`
      regenerateControllersRef.current[requestKey]?.abort()
      const controller = new AbortController()
      regenerateControllersRef.current[requestKey] = controller

      options.setSession((prev) => (prev ? markDraftSectionRegenerating(prev, questionId, sectionKey) : prev))

      regenerateQuestionLibrarySection(
        activeSession.previewId,
        { question_id: questionId, section_key: sectionKey },
        (event) => {
          if (event.type === 'done') {
            const content = String((event as any).data?.content || '').trim()
            options.setSession((prev) => (prev ? applyRegeneratedDraftSection(prev, questionId, sectionKey, content) : prev))
            options.pushToast({
              id: `ai-generate-regenerate-done-${questionId}-${sectionKey}`,
              title: `${sectionKey === 'stem' ? '题干' : sectionKey === 'answer' ? '答案' : '解析'} 已更新`,
              status: 'completed',
            })
            return
          }

          if (event.type === 'error') {
            options.setSession((prev) => (prev ? failDraftSectionRegeneration(prev, questionId, sectionKey) : prev))
            const message = String((event as any).data?.message || '片段重生成失败').trim() || '片段重生成失败'
            options.pushToast({ id: `ai-generate-regenerate-error-${questionId}-${sectionKey}`, title: message, status: 'failed' })
          }
        },
        (error) => {
          options.setSession((prev) => (prev ? failDraftSectionRegeneration(prev, questionId, sectionKey) : prev))
          options.pushToast({
            id: `ai-generate-regenerate-network-${questionId}-${sectionKey}`,
            title: error.message || '片段重生成失败',
            status: 'failed',
          })
        },
        () => {
          delete regenerateControllersRef.current[requestKey]
          options.setSession((prev) => {
            if (!prev) return prev
            const target = prev.drafts.find((draft) => draft.questionId === questionId)
            if (!target) return prev
            if (target.sections[sectionKey].status === 'streaming') {
              return finalizeDraftSectionRegeneration(prev, questionId, sectionKey)
            }
            return prev
          })
        },
        { signal: controller.signal }
      )
    },
    [options]
  )

  const handleConfirmDraft = useCallback(
    async (questionId: string) => {
      if (!options.session?.sessionId) return
      const draft = options.session.drafts.find((item) => item.questionId === questionId)
      if (!draft || draft.reviewStatus === 'committed') return

      try {
        await confirmQuestionLibrarySessionQuestion(options.session.sessionId, questionId)
        await options.syncSessionFromServer(options.session.sessionId)
        await options.lib.refreshList()
        options.pushToast({ id: `ai-generate-confirm-${questionId}`, title: '该题已审核通过并入库', status: 'completed' })
      } catch (error: any) {
        options.pushToast({ id: `ai-generate-confirm-${questionId}`, title: error?.message || '审核入库失败', status: 'failed' })
      }
    },
    [options]
  )

  const handleDiscard = useCallback(async () => {
    if (!options.session?.previewId) {
      options.setSession(null)
      options.setSearchParams({})
      return
    }
    setIsDiscarding(true)
    try {
      await discardQuestionLibraryPreview(options.session.previewId)
      options.tasks.clearDraftPreview()
      options.onDisableAutoAppend()
      if (options.session.sessionId) await options.syncSessionFromServer(options.session.sessionId)
      options.pushToast({ id: `ai-generate-discard-${options.session.previewId}`, title: '草稿已归档', status: 'completed' })
    } catch (error: any) {
      options.pushToast({ id: `ai-generate-discard-failed-${options.session.previewId}`, title: error?.message || '归档失败', status: 'failed' })
    } finally {
      setIsDiscarding(false)
    }
  }, [options])

  return {
    draftRefs,
    isDiscarding,
    handleDiscard,
    handleConfirmDraft,
    handleRegenerateSection,
    handleSectionChange,
    handleToggleSectionLock,
  }
}

