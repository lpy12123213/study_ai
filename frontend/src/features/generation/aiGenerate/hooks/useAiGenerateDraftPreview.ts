import { useEffect, useMemo, useState } from 'react'
import {
  commitQuestionLibraryPreview,
  discardQuestionLibraryPreview,
  type QuestionLibraryDraftQuestion,
} from '@/api/questionLibrary'
import type { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'
import type { useQuestionLibraryTasks } from '@/features/generation/questionLibrary/hooks/useQuestionLibraryTasks'
import { useNotificationStore } from '@/stores/useNotificationStore'
import { readString } from '@/lib/record'

interface UseAiGenerateDraftPreviewOptions {
  lib: ReturnType<typeof useQuestionLibrary>
  tasks: ReturnType<typeof useQuestionLibraryTasks>
}

export function useAiGenerateDraftPreview({ lib, tasks }: UseAiGenerateDraftPreviewOptions) {
  const pushToast = useNotificationStore((s) => s.pushToast)

  const [draftQuestions, setDraftQuestions] = useState<QuestionLibraryDraftQuestion[]>([])
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [isCommitting, setIsCommitting] = useState(false)
  const [isDiscarding, setIsDiscarding] = useState(false)

  const previewId = String(tasks.draftPreview?.previewId || '').trim()

  useEffect(() => {
    if (!tasks.draftPreview) {
      setDraftQuestions([])
      setPreviewError(null)
      return
    }
    setDraftQuestions(
      (tasks.draftPreview.draftQuestions || []).map((q) => ({
        ...q,
        keep: q.keep === false ? false : true,
      }))
    )
    setPreviewError(null)
  }, [tasks.draftPreview])

  const commitPreview = async () => {
    if (!previewId) return
    if (isCommitting) return
    const kept = draftQuestions.filter((q) => q.keep)
    if (kept.length === 0) {
      setPreviewError('请至少选择 1 道题入库')
      return
    }

    setIsCommitting(true)
    setPreviewError(null)
    try {
      const res = await commitQuestionLibraryPreview(previewId, draftQuestions)
      pushToast({
        id: `ql-preview-commit-${previewId}`,
        title: `已入库 ${Number(res.inserted || 0)} 道题`,
        status: 'completed',
      })
      tasks.clearDraftPreview()
      await lib.refreshList()
      await lib.refreshDetail()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : readString(err, 'message')
      setPreviewError(msg || '入库失败')
      pushToast({ id: `ql-preview-commit-failed-${previewId}`, title: '入库失败', status: 'failed' })
    } finally {
      setIsCommitting(false)
    }
  }

  const discardPreview = async () => {
    if (!previewId) return
    if (isDiscarding) return
    const ok = confirm('确定要丢弃本次生成的草稿吗？')
    if (!ok) return

    setIsDiscarding(true)
    setPreviewError(null)
    try {
      await discardQuestionLibraryPreview(previewId)
      pushToast({ id: `ql-preview-discard-${previewId}`, title: '草稿已丢弃', status: 'completed' })
      tasks.clearDraftPreview()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : readString(err, 'message')
      setPreviewError(msg || '丢弃失败')
      pushToast({ id: `ql-preview-discard-failed-${previewId}`, title: '丢弃失败', status: 'failed' })
    } finally {
      setIsDiscarding(false)
    }
  }

  const meta = useMemo(() => {
    if (!tasks.draftPreview) return null
    return {
      subject: tasks.draftPreview.subject,
      topic: tasks.draftPreview.topic,
      count: tasks.draftPreview.count,
      previewId: tasks.draftPreview.previewId,
    }
  }, [tasks.draftPreview])

  return {
    draftPreview: tasks.draftPreview,
    meta,
    draftQuestions,
    setDraftQuestions,
    previewError,
    isCommitting,
    isDiscarding,
    commitPreview,
    discardPreview,
  }
}
