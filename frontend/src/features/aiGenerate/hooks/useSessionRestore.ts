import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { archiveQuestionLibrarySession, getQuestionLibrarySession, listQuestionLibrarySessions } from '@/api/questionLibrary'
import type { AiGenerateSessionMode, AiGenerateStudioSession } from '@/features/aiGenerate/types'
import { historySort } from '@/features/aiGenerate/studioUtils'
import { reduceSessionDetailToSession, reduceTaskPreviewToSession } from '@/features/aiGenerate/useAiGenerateSession'

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

  const [missionText, setMissionText] = useState(DEFAULT_MISSION)
  const [difficulty, setDifficulty] = useState('中等')
  const [questionType, setQuestionType] = useState('')
  const [count, setCount] = useState('5')
  const [useStudyArchive, setUseStudyArchive] = useState(true)
  const [useReferenceQuestions, setUseReferenceQuestions] = useState(true)
  const [referenceSource, setReferenceSource] = useState<'any' | 'gaokao' | 'mock' | 'joint'>('any')
  const [referenceYearRange, setReferenceYearRange] = useState<'all' | '3' | '5'>('all')
  const [mode, setMode] = useState<AiGenerateSessionMode>('standard')
  const [gradeId, setGradeId] = useState('')
  const [textbookVersionId, setTextbookVersionId] = useState('')
  const [selectedKnowledgePointIds, setSelectedKnowledgePointIds] = useState<string[]>([])
  const [selectedKnowledgePointLabels, setSelectedKnowledgePointLabels] = useState<string[]>([])
  const [session, setSession] = useState<AiGenerateStudioSession | null>(null)
  const [historyOpen, setHistoryOpen] = useState(true)
  const [workflowOpen, setWorkflowOpen] = useState(true)

  const activeSessionId = String(searchParams.get('session') || '').trim()
  const lastLoadedSessionSignatureRef = useRef('')
  const optimisticStopRequestedRef = useRef<boolean | null>(null)

  const hydrateComposerFromSession = useCallback(
    (next: AiGenerateStudioSession) => {
      setMissionText(next.mission.topic || DEFAULT_MISSION)
      setDifficulty(next.mission.difficulty || '')
      setQuestionType(next.mission.questionType || '')
      setCount(String(next.mission.count || 5))
      setUseStudyArchive(Boolean(next.mission.useStudyArchive))
      setUseReferenceQuestions(next.mission.useReferenceQuestions !== false)
      setReferenceSource((String(next.mission.referenceSource || 'any').trim() || 'any') as 'any' | 'gaokao' | 'mock' | 'joint')
      setReferenceYearRange((String(next.mission.referenceYearRange || 'all').trim() || 'all') as 'all' | '3' | '5')
      setMode(next.mode)
      setGradeId(next.mission.gradeId || '')
      setTextbookVersionId(next.mission.textbookVersionId || '')
      setSelectedKnowledgePointIds([...(next.mission.knowledgePointIds || [])])
      setSelectedKnowledgePointLabels([...(next.mission.knowledgePoints || [])])

      const nextSubject = String(next.mission.subject || '').trim()
      if (nextSubject && nextSubject !== currentSubject) {
        onSubjectChange(nextSubject)
      }
    },
    [currentSubject, onSubjectChange]
  )

  const syncSessionFromServer = useCallback(
    async (sessionId: string) => {
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
      hydrateComposerFromSession(next)
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

    setSession(next)
    hydrateComposerFromSession(next)
  }, [activeSessionId, hydrateComposerFromSession, sessionDetailQuery.data])

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
      setSession(null)
      setSearchParams({ session: sid })
      lastLoadedSessionSignatureRef.current = ''

      try {
        await syncSessionFromServer(sid)
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
