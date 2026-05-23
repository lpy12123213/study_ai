import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { stopQuestionLibrarySession } from '@/api/questionLibrary'
import { generateId } from '@/lib/utils'
import { appendLatexConstraint } from '@/features/generation/aiGenerate/latexRules'
import { clampCount } from '@/features/generation/aiGenerate/studioUtils'
import type { AiGenerateSessionMode, AiGenerateStudioSession } from '@/features/generation/aiGenerate/types'
import { createQueuedSession, setSessionStopRequested } from '@/features/generation/aiGenerate/useAiGenerateSession'

type ToastStatus = 'completed' | 'failed'

interface ToastPayload {
  id: string
  title: string
  status: ToastStatus
}

interface QuestionLibraryTasksLike {
  // Use `any` here: `useQuestionLibraryTasks().runGenerate` has a specific payload type,
  // and strict function type variance makes it hard to express without importing it.
  runGenerate: (payload: any) => string
  draftPreview: unknown
}

interface UseInfiniteModeOptions {
  subject: string
  pushToast: (toast: ToastPayload) => void
  tasks: QuestionLibraryTasksLike
  mode: AiGenerateSessionMode
  setMode: (mode: AiGenerateSessionMode) => void
  session: AiGenerateStudioSession | null
  setSession: React.Dispatch<React.SetStateAction<AiGenerateStudioSession | null>>
  activeSessionId: string
  setSearchParams: (params: Record<string, string>) => void
  syncSessionFromServer: (sessionId: string) => Promise<AiGenerateStudioSession | null>
  optimisticStopRequestedRef: React.MutableRefObject<boolean | null>
  missionText: string
  difficulty: string
  questionType: string
  count: string
  useStudyArchive: boolean
  useReferenceQuestions: boolean
  referenceSource: 'any' | 'gaokao' | 'mock' | 'joint'
  referenceYearRange: 'all' | '3' | '5'
  gradeId: string
  textbookVersionId: string
  selectedKnowledgePointIds: string[]
  selectedKnowledgeNodeLabels: string[]
  isGenerating: boolean
}

export function useInfiniteMode(options: UseInfiniteModeOptions) {
  const {
    subject,
    pushToast,
    tasks,
    mode,
    setMode: _setMode,
    session,
    setSession,
    activeSessionId,
    setSearchParams,
    syncSessionFromServer,
    optimisticStopRequestedRef,
    missionText,
    difficulty,
    questionType,
    count,
    useStudyArchive,
    useReferenceQuestions,
    referenceSource,
    referenceYearRange,
    gradeId,
    textbookVersionId,
    selectedKnowledgePointIds,
    selectedKnowledgeNodeLabels,
    isGenerating,
  } = options

  const [autoAppendEnabled, setAutoAppendEnabled] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const lastAutoAppendSourceTaskRef = useRef('')

  useEffect(() => {
    if (mode !== 'infinite') {
      setAutoAppendEnabled(false)
    }
  }, [mode])

  const currentSessionId = String(session?.sessionId || '').trim()

  useEffect(() => {
    const doneTaskId = String((tasks.draftPreview as any)?.taskId || '').trim()
    if (!autoAppendEnabled || mode !== 'infinite') return
    if (!doneTaskId || !currentSessionId) return
    if (isGenerating) return
    if (session?.stopRequested) return
    if (lastAutoAppendSourceTaskRef.current === doneTaskId) return

    lastAutoAppendSourceTaskRef.current = doneTaskId

    const nextTaskId = tasks.runGenerate({
      subject,
      topic: appendLatexConstraint(missionText.trim()),
      difficulty: difficulty.trim(),
      question_type: questionType.trim(),
      count: clampCount(count),
      use_study_archive: useStudyArchive,
      use_reference_questions: useReferenceQuestions,
      reference_source: referenceSource,
      reference_year_range: referenceYearRange,
      session_id: currentSessionId,
      mode: 'infinite',
      grade_id: gradeId || undefined,
      textbook_version_id: textbookVersionId || undefined,
      knowledge_point_ids: selectedKnowledgePointIds,
      knowledge_points: selectedKnowledgeNodeLabels,
      append: true,
      stream_reasoning: true,
    })

    setSession((prev) =>
      prev
        ? {
            ...prev,
            taskId: nextTaskId,
            status: 'running',
            stopRequested: false,
          }
        : prev
    )
  }, [
    autoAppendEnabled,
    count,
    currentSessionId,
    difficulty,
    gradeId,
    isGenerating,
    missionText,
    mode,
    questionType,
    referenceSource,
    referenceYearRange,
    selectedKnowledgeNodeLabels,
    selectedKnowledgePointIds,
    session?.stopRequested,
    subject,
    tasks,
    tasks.draftPreview,
    textbookVersionId,
    useReferenceQuestions,
    useStudyArchive,
  ])

  const startGeneration = useCallback(() => {
    const nextCount = clampCount(count)
    const rawMission = missionText.trim()
    const normalizedSubject = subject.trim()
    if (!normalizedSubject || !rawMission) {
      pushToast({ id: 'ai-generate-missing-input', title: '请先填写学科和任务描述', status: 'failed' })
      return
    }

    const topic = appendLatexConstraint(rawMission)
    const continuingInfinite = mode === 'infinite' && Boolean(session?.sessionId)
    const nextSessionId =
      mode === 'infinite'
        ? String(session?.sessionId || activeSessionId || `ql-session-${generateId()}`).trim()
        : String(session?.sessionId || '').trim()

    lastAutoAppendSourceTaskRef.current = ''
    optimisticStopRequestedRef.current = mode === 'infinite' ? false : null

    const nextTaskId = tasks.runGenerate({
      subject: normalizedSubject,
      topic,
      difficulty: difficulty.trim(),
      question_type: questionType.trim(),
      count: nextCount,
      use_study_archive: useStudyArchive,
      use_reference_questions: useReferenceQuestions,
      reference_source: referenceSource,
      reference_year_range: referenceYearRange,
      session_id: mode === 'infinite' ? nextSessionId : continuingInfinite ? session?.sessionId : undefined,
      mode,
      grade_id: gradeId || undefined,
      textbook_version_id: textbookVersionId || undefined,
      knowledge_point_ids: selectedKnowledgePointIds,
      knowledge_points: selectedKnowledgeNodeLabels,
      append: continuingInfinite,
      stream_reasoning: true,
    })

    setAutoAppendEnabled(mode === 'infinite')

    if (continuingInfinite && session) {
      setSession({
        ...session,
        sessionId: nextSessionId,
        taskId: nextTaskId,
        status: 'running',
        stopRequested: false,
        mode,
        mission: {
          ...session.mission,
          subject: normalizedSubject,
          topic,
          count: nextCount,
          difficulty: difficulty.trim(),
          questionType: questionType.trim(),
          useStudyArchive,
          useReferenceQuestions,
          referenceSource,
          referenceYearRange,
          gradeId: gradeId || '',
          textbookVersionId: textbookVersionId || '',
          knowledgePointIds: [...selectedKnowledgePointIds],
          knowledgePoints: [...selectedKnowledgeNodeLabels],
        },
      })
      return
    }

    setSession(
      createQueuedSession({
        sessionId: mode === 'infinite' ? nextSessionId : '',
        taskId: nextTaskId,
        subject: normalizedSubject,
        topic,
        count: nextCount,
        mode,
        difficulty: difficulty.trim(),
        questionType: questionType.trim(),
        useStudyArchive,
        useReferenceQuestions,
        referenceSource,
        referenceYearRange,
        gradeId: gradeId || '',
        textbookVersionId: textbookVersionId || '',
        knowledgePointIds: [...selectedKnowledgePointIds],
        knowledgePoints: [...selectedKnowledgeNodeLabels],
      })
    )

    if (mode === 'infinite' && nextSessionId) {
      setSearchParams({ session: nextSessionId })
    } else {
      setSearchParams({})
    }
  }, [
    activeSessionId,
    count,
    difficulty,
    gradeId,
    missionText,
    mode,
    optimisticStopRequestedRef,
    pushToast,
    questionType,
    referenceSource,
    referenceYearRange,
    selectedKnowledgeNodeLabels,
    selectedKnowledgePointIds,
    session,
    setSearchParams,
    setSession,
    subject,
    tasks,
    textbookVersionId,
    useReferenceQuestions,
    useStudyArchive,
  ])

  const stopAppend = useCallback(async () => {
    if (!session) return
    setIsStopping(true)
    try {
      setAutoAppendEnabled(false)
      optimisticStopRequestedRef.current = true
      if (session.sessionId) {
        await stopQuestionLibrarySession(session.sessionId)
        await syncSessionFromServer(session.sessionId)
      } else {
        setSession(setSessionStopRequested(session, true))
      }
      pushToast({ id: 'ai-generate-stop', title: '已停止继续追加', status: 'completed' })
    } catch (error: any) {
      optimisticStopRequestedRef.current = null
      pushToast({ id: 'ai-generate-stop-failed', title: error?.message || '停止失败', status: 'failed' })
    } finally {
      setIsStopping(false)
    }
  }, [optimisticStopRequestedRef, pushToast, session, setSession, syncSessionFromServer])

  const primaryActionLabel = useMemo(() => {
    if (isGenerating) return '生成中'
    if (mode === 'infinite' && session?.sessionId) return '继续生成'
    return '开始生成'
  }, [isGenerating, mode, session?.sessionId])

  return {
    autoAppendEnabled,
    setAutoAppendEnabled,
    isStopping,
    startGeneration,
    stopAppend,
    primaryActionLabel,
  }
}
