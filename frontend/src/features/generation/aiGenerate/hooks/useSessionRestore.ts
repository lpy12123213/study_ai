import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { archiveQuestionLibrarySession, getQuestionLibrarySession, listQuestionLibrarySessions } from '@/api/questionLibrary'
import type { AiGenerateSessionMode, AiGenerateStudioSession } from '@/features/generation/aiGenerate/types'
import { historySort } from '@/features/generation/aiGenerate/studioUtils'
import { reduceSessionDetailToSession, reduceTaskPreviewToSession } from '@/features/generation/aiGenerate/useAiGenerateSession'

const DEFAULT_MISSION =
  '为高一数学生成 5 道函数单调性中等难度题，包含答案和解析，并优先参考最近自学资料。'

type ToastStatus = 'completed' | 'failed'

interface ToastPayload {
  id: string
  title: string
  status: ToastStatus
}

interface QuestionLibraryTasksLike {
  draftPreview: unknown
  clearDraftPreview: () => void
}

interface UseSessionRestoreOptions {
  currentSubject: string
  onSubjectChange: (subject: string) => void
  tasks: QuestionLibraryTasksLike
  onBeforeRestore?: () => void
  pushToast: (toast: ToastPayload) => void
}

export function useSessionRestore(options: UseSessionRestoreOptions) {
  const { currentSubject, onSubjectChange, tasks, onBeforeRestore, pushToast } = options
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()

  const [missionText, setMissionTextState] = useState(DEFAULT_MISSION)
  const [difficulty, setDifficultyState] = useState('中等')
  const [questionType, setQuestionTypeState] = useState('')
  const [count, setCountState] = useState('5')
  const [useStudyArchive, setUseStudyArchiveState] = useState(true)
  const [useReferenceQuestions, setUseReferenceQuestionsState] = useState(true)
  const [referenceSource, setReferenceSourceState] = useState<'any' | 'gaokao' | 'mock' | 'joint'>('any')
  const [referenceYearRange, setReferenceYearRangeState] = useState<'all' | '3' | '5'>('all')
  const [mode, setModeState] = useState<AiGenerateSessionMode>('standard')
  const [gradeId, setGradeIdState] = useState('')
  const [textbookVersionId, setTextbookVersionIdState] = useState('')
  const [selectedKnowledgePointIds, setSelectedKnowledgePointIdsState] = useState<string[]>([])
  const [selectedKnowledgePointLabels, setSelectedKnowledgePointLabelsState] = useState<string[]>([])
  const [session, setSession] = useState<AiGenerateStudioSession | null>(null)
  const [historyOpen, setHistoryOpen] = useState(true)
  const [workflowOpen, setWorkflowOpen] = useState(true)

  const activeSessionId = String(searchParams.get('session') || '').trim()
  const lastLoadedSessionSignatureRef = useRef('')
  const optimisticStopRequestedRef = useRef<boolean | null>(null)
  const composerEditedRef = useRef(false)

  const setComposerState = useCallback(<T,>(setter: Dispatch<SetStateAction<T>>, value: SetStateAction<T>) => {
    setter((prev) => {
      const next = typeof value === 'function' ? (value as (previous: T) => T)(prev) : value
      if (!Object.is(next, prev)) {
        composerEditedRef.current = true
      }
      return next
    })
  }, [])

  const setMissionText = useCallback<Dispatch<SetStateAction<string>>>(
    (value) => {
      setComposerState(setMissionTextState, value)
    },
    [setComposerState]
  )
  const setDifficulty = useCallback<Dispatch<SetStateAction<string>>>(
    (value) => {
      setComposerState(setDifficultyState, value)
    },
    [setComposerState]
  )
  const setQuestionType = useCallback<Dispatch<SetStateAction<string>>>(
    (value) => {
      setComposerState(setQuestionTypeState, value)
    },
    [setComposerState]
  )
  const setCount = useCallback<Dispatch<SetStateAction<string>>>(
    (value) => {
      setComposerState(setCountState, value)
    },
    [setComposerState]
  )
  const setUseStudyArchive = useCallback<Dispatch<SetStateAction<boolean>>>(
    (value) => {
      setComposerState(setUseStudyArchiveState, value)
    },
    [setComposerState]
  )
  const setUseReferenceQuestions = useCallback<Dispatch<SetStateAction<boolean>>>(
    (value) => {
      setComposerState(setUseReferenceQuestionsState, value)
    },
    [setComposerState]
  )
  const setReferenceSource = useCallback<Dispatch<SetStateAction<'any' | 'gaokao' | 'mock' | 'joint'>>>(
    (value) => {
      setComposerState(setReferenceSourceState, value)
    },
    [setComposerState]
  )
  const setReferenceYearRange = useCallback<Dispatch<SetStateAction<'all' | '3' | '5'>>>(
    (value) => {
      setComposerState(setReferenceYearRangeState, value)
    },
    [setComposerState]
  )
  const setMode = useCallback<Dispatch<SetStateAction<AiGenerateSessionMode>>>(
    (value) => {
      setComposerState(setModeState, value)
    },
    [setComposerState]
  )
  const setGradeId = useCallback<Dispatch<SetStateAction<string>>>(
    (value) => {
      setComposerState(setGradeIdState, value)
    },
    [setComposerState]
  )
  const setTextbookVersionId = useCallback<Dispatch<SetStateAction<string>>>(
    (value) => {
      setComposerState(setTextbookVersionIdState, value)
    },
    [setComposerState]
  )
  const setSelectedKnowledgePointIds = useCallback<Dispatch<SetStateAction<string[]>>>(
    (value) => {
      setComposerState(setSelectedKnowledgePointIdsState, value)
    },
    [setComposerState]
  )
  const setSelectedKnowledgePointLabels = useCallback<Dispatch<SetStateAction<string[]>>>(
    (value) => {
      setComposerState(setSelectedKnowledgePointLabelsState, value)
    },
    [setComposerState]
  )

  const hydrateComposerFromSession = useCallback(
    (next: AiGenerateStudioSession, options?: { force?: boolean }) => {
      if (composerEditedRef.current && !options?.force) {
        return
      }
      setMissionTextState(next.mission.topic || DEFAULT_MISSION)
      setDifficultyState(next.mission.difficulty || '')
      setQuestionTypeState(next.mission.questionType || '')
      setCountState(String(next.mission.count || 5))
      setUseStudyArchiveState(Boolean(next.mission.useStudyArchive))
      setUseReferenceQuestionsState(next.mission.useReferenceQuestions !== false)
      setReferenceSourceState((String(next.mission.referenceSource || 'any').trim() || 'any') as 'any' | 'gaokao' | 'mock' | 'joint')
      setReferenceYearRangeState((String(next.mission.referenceYearRange || 'all').trim() || 'all') as 'all' | '3' | '5')
      setModeState(next.mode)
      setGradeIdState(next.mission.gradeId || '')
      setTextbookVersionIdState(next.mission.textbookVersionId || '')
      setSelectedKnowledgePointIdsState([...(next.mission.knowledgePointIds || [])])
      setSelectedKnowledgePointLabelsState([...(next.mission.knowledgePoints || [])])
      composerEditedRef.current = false

      const nextSubject = String(next.mission.subject || '').trim()
      if (nextSubject && nextSubject !== currentSubject) {
        onSubjectChange(nextSubject)
      }
    },
    [currentSubject, onSubjectChange]
  )

  const syncSessionFromServer = useCallback(
    async (sessionId: string, options?: { forceHydrateComposer?: boolean }) => {
      const sid = String(sessionId || '').trim()
      if (!sid) return null
      const resp = await getQuestionLibrarySession(sid)
      queryClient.setQueryData(['questionLibrarySession', sid], resp)
      lastLoadedSessionSignatureRef.current = ''

      let next = reduceSessionDetailToSession(resp.session)
      const optimisticStopRequested = optimisticStopRequestedRef.current
      if (optimisticStopRequested !== null) {
        const serverMatches = next.stopRequested === optimisticStopRequested
        if (serverMatches) {
          optimisticStopRequestedRef.current = null
        } else {
          next = {
            ...next,
            stopRequested: optimisticStopRequested,
            status: optimisticStopRequested ? 'stopped' : next.status === 'stopped' ? 'running' : next.status,
          }
        }
      }

      setSession(next)
      hydrateComposerFromSession(next, { force: options?.forceHydrateComposer })
      await queryClient.invalidateQueries({ queryKey: ['questionLibrarySessions'] })
      return next
    },
    [hydrateComposerFromSession, queryClient]
  )

  const sessionsQuery = useQuery({
    queryKey: ['questionLibrarySessions'],
    queryFn: listQuestionLibrarySessions,
  })

  const sessionDetailQuery = useQuery({
    queryKey: ['questionLibrarySession', activeSessionId],
    queryFn: () => getQuestionLibrarySession(activeSessionId),
    enabled: Boolean(activeSessionId),
    retry: false,
    refetchInterval: (query) => {
      const incomingStatus = String((query.state.data as any)?.session?.status || '').trim().toLowerCase()
      const localStatus = String(session?.status || '').trim().toLowerCase()
      return incomingStatus === 'running' || localStatus === 'running' ? 2500 : false
    },
    refetchIntervalInBackground: true,
  })

  useEffect(() => {
    if (!sessionDetailQuery.data?.session) return
    if (!activeSessionId) return
    const detail = sessionDetailQuery.data.session
    const signature = JSON.stringify([
      activeSessionId,
      String(detail.status || ''),
      Number(detail.updated_at_s || 0),
      String(detail.latest_task_id || ''),
      Array.isArray(detail.draft_questions) ? detail.draft_questions.length : 0,
      Array.isArray(detail.reasoning_blocks) ? detail.reasoning_blocks.length : 0,
      Array.isArray(detail.task_events) ? detail.task_events.length : 0,
    ])
    if (lastLoadedSessionSignatureRef.current === signature) return
    lastLoadedSessionSignatureRef.current = signature

    let next = reduceSessionDetailToSession(detail)
    const optimisticStopRequested = optimisticStopRequestedRef.current
    if (optimisticStopRequested !== null) {
      const serverMatches = next.stopRequested === optimisticStopRequested
      if (serverMatches) {
        optimisticStopRequestedRef.current = null
      } else {
        next = {
          ...next,
          stopRequested: optimisticStopRequested,
          status: optimisticStopRequested ? 'stopped' : next.status === 'stopped' ? 'running' : next.status,
        }
      }
    }

    const isSameSession = session?.sessionId === next.sessionId
    const isPollingRunningSession = isSameSession && String(next.status || '').trim() === 'running'
    setSession(next)
    if (!isPollingRunningSession) {
      hydrateComposerFromSession(next)
    }
  }, [activeSessionId, hydrateComposerFromSession, session?.sessionId, sessionDetailQuery.data])

  useEffect(() => {
    if (!tasks.draftPreview) return
    const next = reduceTaskPreviewToSession(tasks.draftPreview as any)
    setSession(next)
    hydrateComposerFromSession(next)
    if (next.sessionId) {
      lastLoadedSessionSignatureRef.current = ''
      setSearchParams({ session: next.sessionId })
      void queryClient.invalidateQueries({ queryKey: ['questionLibrarySessions'] })
    }
  }, [hydrateComposerFromSession, queryClient, setSearchParams, tasks.draftPreview])

  const historySessions = useMemo(() => historySort((sessionsQuery.data as any)?.sessions || []), [sessionsQuery.data])

  const restoreSession = useCallback(
    async (sessionId: string) => {
      const sid = String(sessionId || '').trim()
      if (!sid) return
      onBeforeRestore?.()
      tasks.clearDraftPreview()
      composerEditedRef.current = false
      setSession(null)
      setSearchParams({ session: sid })
      lastLoadedSessionSignatureRef.current = ''

      try {
        await syncSessionFromServer(sid, { forceHydrateComposer: true })
      } catch {
        lastLoadedSessionSignatureRef.current = ''
      }
    },
    [onBeforeRestore, setSearchParams, syncSessionFromServer, tasks]
  )

  const archiveSession = useCallback(
    async (sessionId: string) => {
      try {
        await archiveQuestionLibrarySession(sessionId)
        if (session?.sessionId === sessionId) {
          await syncSessionFromServer(sessionId)
        } else {
          await queryClient.invalidateQueries({ queryKey: ['questionLibrarySessions'] })
        }
        pushToast({ id: `ai-generate-archive-${sessionId}`, title: '会话已归档', status: 'completed' })
      } catch (error: any) {
        pushToast({
          id: `ai-generate-archive-failed-${sessionId}`,
          title: error?.message || '归档失败',
          status: 'failed',
        })
      }
    },
    [pushToast, queryClient, session?.sessionId, syncSessionFromServer]
  )

  return {
    DEFAULT_MISSION,
    activeSessionId,
    setSearchParams,
    sessionsQuery,
    sessionDetailQuery,
    historySessions,
    session,
    setSession,
    missionText,
    setMissionText,
    difficulty,
    setDifficulty,
    questionType,
    setQuestionType,
    count,
    setCount,
    useStudyArchive,
    setUseStudyArchive,
    useReferenceQuestions,
    setUseReferenceQuestions,
    referenceSource,
    setReferenceSource,
    referenceYearRange,
    setReferenceYearRange,
    mode,
    setMode,
    gradeId,
    setGradeId,
    textbookVersionId,
    setTextbookVersionId,
    selectedKnowledgePointIds,
    setSelectedKnowledgePointIds,
    selectedKnowledgePointLabels,
    setSelectedKnowledgePointLabels,
    historyOpen,
    setHistoryOpen,
    workflowOpen,
    setWorkflowOpen,
    restoreSession,
    archiveSession,
    syncSessionFromServer,
    optimisticStopRequestedRef,
  }
}
