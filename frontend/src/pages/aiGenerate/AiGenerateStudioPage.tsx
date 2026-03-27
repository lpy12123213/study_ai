import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, History, Loader2, PanelsTopLeft, SquareArrowOutUpRight } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  archiveQuestionLibrarySession,
  commitQuestionLibraryPreview,
  confirmQuestionLibrarySessionQuestion,
  discardQuestionLibraryPreview,
  getQuestionLibrarySession,
  listQuestionLibrarySessions,
  regenerateQuestionLibrarySection,
  stopQuestionLibrarySession,
  unconfirmQuestionLibrarySessionQuestion,
} from '@/api/questionLibrary'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { TaskTimeline } from '@/components/task/TaskTimeline'
import { taskEventToStep } from '@/components/task/taskEventAdapter'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { useSubjectFilters, useSubjectKnowledgeTree, useSubjects } from '@/hooks/useSubjects'
import { generateId } from '@/lib/utils'
import { useToastStore } from '@/stores/useToastStore'
import { useTaskStore } from '@/stores/useTaskStore'
import { ContextRail } from '@/pages/aiGenerate/ContextRail'
import { ConfirmedShelf } from '@/pages/aiGenerate/ConfirmedShelf'
import { GenerationStream } from '@/pages/aiGenerate/GenerationStream'
import { humanizeAiGenerateTaskError } from '@/pages/aiGenerate/humanizeTaskError'
import { appendLatexConstraint } from '@/pages/aiGenerate/latexRules'
import { MissionComposer } from '@/pages/aiGenerate/MissionComposer'
import type { AiGenerateKnowledgeNode, AiGenerateSessionMode, AiGenerateStudioSession } from '@/pages/aiGenerate/types'
import {
  applyRegeneratedDraftSection,
  createQueuedSession,
  failDraftSectionRegeneration,
  finalizeDraftSectionRegeneration,
  markDraftSectionRegenerating,
  reduceSessionDetailToSession,
  reduceTaskPreviewToSession,
  setSessionStopRequested,
  toCommitQuestions,
  toggleDraftSectionLock,
  updateDraftSection,
} from '@/pages/aiGenerate/useAiGenerateSession'
import { useQuestionLibrary } from '@/pages/questionLibrary/hooks/useQuestionLibrary'
import { useQuestionLibraryTasks } from '@/pages/questionLibrary/hooks/useQuestionLibraryTasks'
import type { TaskStep } from '@/types'

const DEFAULT_MISSION =
  '为高一数学生成 5 道函数单调性中等难度题，包含答案和解析，并优先参考最近自学资料。'
const EMPTY_TASK_STEPS: TaskStep[] = []

interface ReasonConsoleEntry {
  id: string
  label: '原始 Reason' | '事件 Trace'
  stageLabel: string
  content: string
  createdAt?: string
}

function clampCount(raw: string): number {
  const value = Number(raw)
  if (!Number.isFinite(value)) return 5
  return Math.max(1, Math.min(10, Math.floor(value)))
}

function statusLabel(status: string): string {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'pending_review') return '待审核'
  if (normalized === 'partial_failure') return '部分完成'
  if (normalized === 'archived_discarded') return '已归档'
  if (normalized === 'committed') return '已入库'
  if (normalized === 'stopped') return '已停止'
  if (normalized === 'running') return '运行中'
  if (normalized === 'failed') return '失败'
  if (normalized === 'archived') return '已归档'
  return normalized || '未开始'
}

function flattenKnowledgeNodes(nodes: AiGenerateKnowledgeNode[]): Record<string, AiGenerateKnowledgeNode> {
  const out: Record<string, AiGenerateKnowledgeNode> = {}
  const visit = (node: AiGenerateKnowledgeNode) => {
    out[node.id] = node
    ;(node.children || []).forEach(visit)
  }
  nodes.forEach(visit)
  return out
}

function toReasonEntries(
  session: AiGenerateStudioSession | null,
  currentTaskId: string,
  liveEvents: Array<{ type?: string; data?: any; created_at?: string; taskId?: string }>
): ReasonConsoleEntry[] {
  const entries: ReasonConsoleEntry[] = []
  const persistedEvents = Array.isArray(session?.taskEvents) ? session?.taskEvents || [] : []
  const statusEvents = [...persistedEvents, ...liveEvents].filter((event) => String(event?.type || '') === 'reasoning_status')
  const liveBlocks = liveEvents
    .filter((event) => String(event?.type || '') === 'reasoning_delta')
    .map((event, index) => ({
      id: `live-reason-${index}-${String(event.created_at || '')}`,
      taskId: String(event.taskId || '').trim(),
      stageLabel: String(event.data?.stage_label || event.data?.stage_id || '').trim() || '推理过程',
      source: String(event.data?.source || 'trace').trim() || 'trace',
      content: String(event.data?.content || '').trim(),
      createdAt: String(event.created_at || '').trim() || undefined,
    }))
    .filter((item) => item.content)

  const persistedBlocks = (session?.reasoningBlocks || []).filter((block) => {
    if (!currentTaskId || liveBlocks.length === 0) return true
    return String(block.taskId || '').trim() !== currentTaskId
  })

  // Aggregate consecutive reasoning deltas with same stageLabel+source into one entry.
  // This prevents streaming chunks from being shown as many tiny separate cards.
  function aggregateBlocks(blocks: Array<{ id: string; stageLabel?: string; source?: string; content: string; createdAt?: string }>): ReasonConsoleEntry[] {
    const result: ReasonConsoleEntry[] = []
    let current: ReasonConsoleEntry | null = null
    let currentKey = ''
    for (const block of blocks) {
      const label: '原始 Reason' | '事件 Trace' = String(block.source || '').trim() === 'raw' ? '原始 Reason' : '事件 Trace'
      const stageLabel = String(block.stageLabel || '').trim() || '推理过程'
      const key = `${label}:${stageLabel}`
      if (current && key === currentKey) {
        // Same stage+source: append content to the running entry
        current.content += String(block.content || '').trim()
      } else {
        // Stage or source changed: start a new entry
        if (current) result.push(current)
        current = {
          id: String(block.id || `${stageLabel}-${block.createdAt || ''}`),
          label,
          stageLabel,
          content: String(block.content || '').trim(),
          createdAt: block.createdAt,
        }
        currentKey = key
      }
    }
    if (current) result.push(current)
    return result
  }

  for (const event of statusEvents) {
    const mode = String(event?.data?.mode || 'trace').trim() || 'trace'
    const message = String(event?.data?.message || '').trim()
    if (!message) continue
    entries.push({
      id: `reason-status-${String(event.created_at || '')}-${mode}-${message}`,
      label: mode === 'raw' ? '原始 Reason' : '事件 Trace',
      stageLabel: String(event?.data?.stage_label || event?.data?.stage_id || '').trim() || '推理过程',
      content: message,
      createdAt: String(event.created_at || '').trim() || undefined,
    })
  }

  entries.push(...aggregateBlocks([...persistedBlocks, ...liveBlocks]))

  const deduped = new Map<string, ReasonConsoleEntry>()
  for (const entry of entries) {
    const key = `${entry.label}:${entry.stageLabel}:${entry.content.slice(0, 200)}`
    if (!deduped.has(key)) deduped.set(key, entry)
  }
  return [...deduped.values()].slice(-40)
}

function historySort<T extends { updated_at_s?: number; created_at_s?: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => Number(b.updated_at_s || b.created_at_s || 0) - Number(a.updated_at_s || a.created_at_s || 0))
}

export function AiGenerateStudioPage() {
  const queryClient = useQueryClient()
  const { data: subjects } = useSubjects()
  const pushToast = useToastStore((state) => state.pushToast)
  const [searchParams, setSearchParams] = useSearchParams()

  const lib = useQuestionLibrary({
    initialFilters: {
      origin: 'ai',
      hidden: '0',
      sort: 'updated_at',
      order: 'desc',
    },
  })

  const tasks = useQuestionLibraryTasks({
    filters: lib.filters,
    restoreLatestPreview: true,
    onDone: async () => {
      await lib.refreshList()
      await lib.refreshDetail()
    },
  })

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
  const [isCommitting, setIsCommitting] = useState(false)
  const [isDiscarding, setIsDiscarding] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(true)
  const [workflowOpen, setWorkflowOpen] = useState(true)
  const [autoAppendEnabled, setAutoAppendEnabled] = useState(false)

  const activeSessionId = String(searchParams.get('session') || '').trim()
  const draftRefs = useRef<Array<HTMLDivElement | null>>([])
  const regenerateControllersRef = useRef<Record<string, AbortController>>({})
  const lastAutoAppendSourceTaskRef = useRef('')
  const lastLoadedSessionIdRef = useRef('')
  const optimisticStopRequestedRef = useRef<boolean | null>(null)

  const { data: subjectFiltersData } = useSubjectFilters(lib.filters.subject || undefined)
  const subjectFilters = subjectFiltersData || {}
  const knowledgeTreeQuery = useSubjectKnowledgeTree(lib.filters.subject || undefined, {
    gradeId: gradeId || undefined,
    textbookVersionId: textbookVersionId || undefined,
  })
  const knowledgeTree = useMemo(
    () => ((knowledgeTreeQuery.data?.nodes || []) as AiGenerateKnowledgeNode[]),
    [knowledgeTreeQuery.data?.nodes]
  )
  const knowledgeNodeMap = useMemo(() => flattenKnowledgeNodes(knowledgeTree), [knowledgeTree])

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
      if (next.mission.subject && next.mission.subject !== lib.filters.subject) {
        lib.setSubject(next.mission.subject)
      }
    },
    [lib]
  )

  const syncSessionFromServer = useCallback(
    async (sessionId: string) => {
      const sid = String(sessionId || '').trim()
      if (!sid) return null
      const resp = await getQuestionLibrarySession(sid)
      queryClient.setQueryData(['questionLibrarySession', sid], resp)
      lastLoadedSessionIdRef.current = ''
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
    if (lastLoadedSessionIdRef.current === signature) return
    lastLoadedSessionIdRef.current = signature
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
    const next = reduceTaskPreviewToSession(tasks.draftPreview)
    setSession(next)
    hydrateComposerFromSession(next)
    if (next.sessionId) {
      lastLoadedSessionIdRef.current = ''
      setSearchParams({ session: next.sessionId })
      void queryClient.invalidateQueries({ queryKey: ['questionLibrarySessions'] })
    }
  }, [hydrateComposerFromSession, queryClient, setSearchParams, tasks.draftPreview])

  useEffect(() => {
    return () => {
      Object.values(regenerateControllersRef.current).forEach((controller) => controller.abort())
      regenerateControllersRef.current = {}
    }
  }, [])

  const activeTask = tasks.preferredTask
  const currentTaskId = String(activeTask?.taskId || session?.taskId || '').trim()
  const activeTasks = useTaskStore((state) => state.activeTasks)
  const activeTaskSteps = useMemo(
    () => (currentTaskId ? activeTasks.get(currentTaskId) || EMPTY_TASK_STEPS : EMPTY_TASK_STEPS),
    [activeTasks, currentTaskId]
  )
  const fallbackTaskSteps = useMemo(() => {
    const persisted = Array.isArray(session?.taskEvents) ? session?.taskEvents : []
    return persisted
      .map((item) =>
        taskEventToStep({
          taskId: String((item as any)?.taskId || currentTaskId),
          seq: Number((item as any)?.seq || 0),
          type: String((item as any)?.type || ''),
          data: (item as any)?.data,
          created_at: String((item as any)?.created_at || ''),
        })
      )
      .filter((item): item is TaskStep => Boolean(item))
  }, [currentTaskId, session?.taskEvents])
  const workflowSteps = activeTaskSteps.length > 0 ? activeTaskSteps : fallbackTaskSteps

  const progress = Math.max(0, Math.min(100, Number(activeTask?.progress || (session?.status === 'committed' ? 100 : 0))))
  const stage = String(activeTask?.stage || '').trim()
  const taskStatus = String(activeTask?.status || '').trim()
  const sessionStatus = String(session?.status || '').trim()
  const isSessionRunning = sessionStatus === 'running'
  const effectiveTaskStatus = isSessionRunning ? 'running' : taskStatus || sessionStatus
  const isGenerating = effectiveTaskStatus === 'running'
  const taskError = String(activeTask?.error || '').trim()
  const taskErrorInfo = useMemo(() => humanizeAiGenerateTaskError(taskError), [taskError])
  const confirmedDrafts = useMemo(() => {
    if (!session) return []
    const ids = new Set(session.confirmedIds)
    return session.drafts.filter((draft) => ids.has(draft.questionId))
  }, [session])
  const currentTaskEvents = tasks.getTaskEvents(currentTaskId)
  const reasonEntries = useMemo(
    () => toReasonEntries(session, currentTaskId, currentTaskEvents),
    [currentTaskEvents, currentTaskId, session]
  )

  const restoreSession = useCallback(
    async (sessionId: string) => {
      setAutoAppendEnabled(false)
      tasks.clearDraftPreview()
      setSession(null)
      setSearchParams({ session: sessionId })
      lastLoadedSessionIdRef.current = ''
      try {
        await syncSessionFromServer(sessionId)
      } catch {
        lastLoadedSessionIdRef.current = ''
      }
    },
    [setSearchParams, syncSessionFromServer, tasks]
  )

  const selectedKnowledgeNodeLabels = useMemo(() => {
    if (selectedKnowledgePointLabels.length > 0) return selectedKnowledgePointLabels
    return selectedKnowledgePointIds
      .map((id) => knowledgeNodeMap[id]?.label || '')
      .filter((item) => item.trim().length > 0)
  }, [knowledgeNodeMap, selectedKnowledgePointIds, selectedKnowledgePointLabels])

  const historySessions = historySort(sessionsQuery.data?.sessions || [])

  useEffect(() => {
    if (mode !== 'infinite') {
      setAutoAppendEnabled(false)
    }
  }, [mode])

  useEffect(() => {
    const doneTaskId = String(tasks.draftPreview?.taskId || '').trim()
    const currentSessionId = String(session?.sessionId || '').trim()
    if (!autoAppendEnabled || mode !== 'infinite') return
    if (!doneTaskId || !currentSessionId) return
    if (isGenerating) return
    if (session?.stopRequested) return
    if (lastAutoAppendSourceTaskRef.current === doneTaskId) return

    lastAutoAppendSourceTaskRef.current = doneTaskId
    const nextTaskId = tasks.runGenerate({
      subject: lib.filters.subject,
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
    difficulty,
    gradeId,
    lib.filters.subject,
    missionText,
    mode,
    questionType,
    referenceSource,
    referenceYearRange,
    selectedKnowledgeNodeLabels,
    selectedKnowledgePointIds,
    session,
    isGenerating,
    tasks,
    tasks.draftPreview,
    textbookVersionId,
    useReferenceQuestions,
    useStudyArchive,
  ])

  const startGeneration = () => {
    const nextCount = clampCount(count)
    const rawMission = missionText.trim()
    const subject = lib.filters.subject.trim()
    if (!subject || !rawMission) {
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
      subject,
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
          subject,
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
        subject,
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
  }

  const handleToggleKnowledgePoint = (node: AiGenerateKnowledgeNode) => {
    setSelectedKnowledgePointIds((prev) => {
      const exists = prev.includes(node.id)
      return exists ? prev.filter((item) => item !== node.id) : [...prev, node.id]
    })
    setSelectedKnowledgePointLabels((prev) => {
      const exists = prev.includes(node.label)
      return exists ? prev.filter((item) => item !== node.label) : [...prev, node.label]
    })
  }

  const handleSectionChange = (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis', content: string) => {
    setSession((prev) => (prev ? updateDraftSection(prev, questionId, sectionKey, content) : prev))
  }

  const handleToggleSectionLock = (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis') => {
    setSession((prev) => (prev ? toggleDraftSectionLock(prev, questionId, sectionKey) : prev))
  }

  const handleRegenerateSection = (questionId: string, sectionKey: 'stem' | 'answer' | 'analysis') => {
    const activeSession = session
    if (!activeSession?.previewId) {
      pushToast({ id: 'ai-generate-regenerate-missing-preview', title: '请等待草稿生成完成后再重生成片段', status: 'failed' })
      return
    }

    const targetDraft = activeSession.drafts.find((draft) => draft.questionId === questionId)
    if (!targetDraft) return
    if (targetDraft.sections[sectionKey].locked) {
      pushToast({ id: `ai-generate-locked-${questionId}-${sectionKey}`, title: '该片段已锁定，请先解锁后再重生成', status: 'failed' })
      return
    }

    const requestKey = `${questionId}:${sectionKey}`
    regenerateControllersRef.current[requestKey]?.abort()
    const controller = new AbortController()
    regenerateControllersRef.current[requestKey] = controller

    setSession((prev) => (prev ? markDraftSectionRegenerating(prev, questionId, sectionKey) : prev))

    regenerateQuestionLibrarySection(
      activeSession.previewId,
      { question_id: questionId, section_key: sectionKey },
      (event) => {
        if (event.type === 'done') {
          const content = String(event.data?.content || '').trim()
          setSession((prev) => (prev ? applyRegeneratedDraftSection(prev, questionId, sectionKey, content) : prev))
          pushToast({
            id: `ai-generate-regenerate-done-${questionId}-${sectionKey}`,
            title: `${sectionKey === 'stem' ? '题干' : sectionKey === 'answer' ? '答案' : '解析'} 已更新`,
            status: 'completed',
          })
          return
        }

        if (event.type === 'error') {
          setSession((prev) => (prev ? failDraftSectionRegeneration(prev, questionId, sectionKey) : prev))
          const message = String(event.data?.message || '片段重生成失败').trim() || '片段重生成失败'
          pushToast({ id: `ai-generate-regenerate-error-${questionId}-${sectionKey}`, title: message, status: 'failed' })
        }
      },
      (error) => {
        setSession((prev) => (prev ? failDraftSectionRegeneration(prev, questionId, sectionKey) : prev))
        pushToast({
          id: `ai-generate-regenerate-network-${questionId}-${sectionKey}`,
          title: error.message || '片段重生成失败',
          status: 'failed',
        })
      },
      () => {
        delete regenerateControllersRef.current[requestKey]
        setSession((prev) => {
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
  }

  const handleConfirmDraft = async (questionId: string) => {
    if (!session?.sessionId) return
    const draft = session.drafts.find((item) => item.questionId === questionId)
    if (!draft) return

    try {
      if (draft.reviewStatus === 'confirmed') {
        await unconfirmQuestionLibrarySessionQuestion(session.sessionId, questionId)
      } else {
        await confirmQuestionLibrarySessionQuestion(session.sessionId, questionId)
      }
      await syncSessionFromServer(session.sessionId)
    } catch (error: any) {
      pushToast({ id: `ai-generate-confirm-${questionId}`, title: error?.message || '确认状态更新失败', status: 'failed' })
    }
  }

  const handleCommit = async () => {
    if (!session?.previewId) {
      pushToast({ id: 'ai-generate-commit-missing-preview', title: '请等待草稿生成完成后再入库', status: 'failed' })
      return
    }
    if (confirmedDrafts.length === 0) {
      pushToast({ id: 'ai-generate-empty-confirmed', title: '请至少确认 1 道题再入库', status: 'failed' })
      return
    }

    setIsCommitting(true)
    try {
      const result = await commitQuestionLibraryPreview(session.previewId, toCommitQuestions(session))
      pushToast({
        id: `ai-generate-commit-${session.previewId}`,
        title: `已入库 ${Number(result.inserted || 0)} 道题`,
        status: 'completed',
      })
      tasks.clearDraftPreview()
      setAutoAppendEnabled(false)
      if (session.sessionId) await syncSessionFromServer(session.sessionId)
      await lib.refreshList()
    } catch (error: any) {
      pushToast({ id: `ai-generate-commit-failed-${session.previewId}`, title: error?.message || '入库失败', status: 'failed' })
    } finally {
      setIsCommitting(false)
    }
  }

  const handleDiscard = async () => {
    if (!session?.previewId) {
      setSession(null)
      setSearchParams({})
      return
    }
    setIsDiscarding(true)
    try {
      await discardQuestionLibraryPreview(session.previewId)
      tasks.clearDraftPreview()
      setAutoAppendEnabled(false)
      if (session.sessionId) await syncSessionFromServer(session.sessionId)
      pushToast({ id: `ai-generate-discard-${session.previewId}`, title: '草稿已归档', status: 'completed' })
    } catch (error: any) {
      pushToast({ id: `ai-generate-discard-failed-${session.previewId}`, title: error?.message || '归档失败', status: 'failed' })
    } finally {
      setIsDiscarding(false)
    }
  }

  const handleStop = async () => {
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
  }

  const handleArchiveSession = async (sessionId: string) => {
    try {
      await archiveQuestionLibrarySession(sessionId)
      if (session?.sessionId === sessionId) {
        await syncSessionFromServer(sessionId)
      } else {
        await queryClient.invalidateQueries({ queryKey: ['questionLibrarySessions'] })
      }
      pushToast({ id: `ai-generate-archive-${sessionId}`, title: '会话已归档', status: 'completed' })
    } catch (error: any) {
      pushToast({ id: `ai-generate-archive-failed-${sessionId}`, title: error?.message || '归档失败', status: 'failed' })
    }
  }

  const primaryActionLabel = useMemo(() => {
    if (isGenerating) return '生成中'
    if (mode === 'infinite' && session?.sessionId) return '继续生成'
    return '开始生成'
  }, [isGenerating, mode, session?.sessionId])

  return (
    <div className="h-full overflow-y-auto bg-[radial-gradient(circle_at_top,_rgba(50,106,255,0.12),_transparent_32%),linear-gradient(180deg,_rgba(248,245,238,0.94),_rgba(246,241,231,0.78))] text-foreground dark:bg-[radial-gradient(circle_at_top,_rgba(92,140,255,0.18),_transparent_40%),radial-gradient(circle_at_70%_0%,_rgba(255,210,140,0.10),_transparent_42%),linear-gradient(180deg,_rgba(14,16,24,1),_rgba(10,12,18,1))]">
      <div className="mx-auto flex min-h-full w-full max-w-[1920px] flex-col gap-6 px-4 py-6 lg:px-5 2xl:px-8">
        <div className="grid gap-5 xl:grid-cols-[260px_minmax(0,1fr)] 2xl:gap-6 2xl:grid-cols-[260px_minmax(0,1.55fr)_320px]">
          <Card className="overflow-hidden rounded-[30px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.97),rgba(247,242,232,0.93))] shadow-[0_20px_50px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.95),rgba(16,18,28,0.94))] dark:shadow-[0_20px_70px_rgba(0,0,0,0.56)]">
            <CardHeader className="border-b border-border/60 pb-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
                    <History className="h-5 w-5" />
                  </div>
                  <div>
                    <CardTitle className="text-lg">会话历史</CardTitle>
                    <div className="text-sm text-muted-foreground">恢复任意一轮 AI 出题的草稿、流程与 reasoning。</div>
                  </div>
                </div>
                <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={() => setHistoryOpen((value) => !value)}>
                  <ChevronDown className={`h-4 w-4 transition-transform ${historyOpen ? '' : '-rotate-90'}`} />
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {historyOpen ? (
                <ScrollArea className="h-[980px]">
                  <div className="space-y-3 p-4">
                    {sessionsQuery.isLoading ? (
                      <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        会话加载中
                      </div>
                    ) : historySessions.length === 0 ? (
                      <div className="rounded-[22px] border border-dashed border-border bg-background/60 px-4 py-8 text-center text-sm text-muted-foreground">
                        还没有会话历史，先从中间工作台启动一轮出题。
                      </div>
                    ) : (
                      historySessions.map((item: any) => {
                        const sid = String(item.session_id || '').trim()
                        const selected = sid === activeSessionId
                        return (
                          <div
                            key={sid}
                            className={`rounded-[24px] border p-4 transition-colors ${
                              selected
                                ? 'border-amber-300 bg-amber-50/80 dark:border-amber-700/60 dark:bg-amber-950/20'
                                : 'border-border/70 bg-background/80'
                            }`}
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="text-xs uppercase tracking-[0.22em] text-muted-foreground">{item.subject || '未命名学科'}</div>
                                <div className="mt-1 truncate text-base font-semibold">{item.topic || '未命名会话'}</div>
                              </div>
                              <Badge variant="outline" className="rounded-full">
                                {statusLabel(String(item.status || ''))}
                              </Badge>
                            </div>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <Badge variant="outline" className="rounded-full">
                                {String(item.mode || 'standard') === 'infinite' ? '无限模式' : '标准模式'}
                              </Badge>
                              <Badge variant="outline" className="rounded-full">
                                {Number(item.count || 0)} 题
                              </Badge>
                              <Badge variant="outline" className="rounded-full">
                                reasoning {Number(item.reasoning_blocks_count || 0)}
                              </Badge>
                            </div>
                            <div className="mt-4 flex flex-wrap items-center gap-2">
                              <Button type="button" size="sm" className="rounded-full" onClick={() => restoreSession(sid)}>
                                恢复会话
                              </Button>
                              <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={() => handleArchiveSession(sid)}>
                                归档
                              </Button>
                            </div>
                          </div>
                        )
                      })
                    )}
                  </div>
                </ScrollArea>
              ) : null}
            </CardContent>
          </Card>

          <div className="flex min-w-0 flex-col gap-6">
            <Card className="overflow-hidden rounded-[30px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(248,244,234,0.94))] shadow-[0_22px_56px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.96),rgba(16,18,28,0.95))] dark:shadow-[0_24px_82px_rgba(0,0,0,0.56)]">
              <CardHeader className="border-b border-border/60 pb-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-200">
                      <PanelsTopLeft className="h-5 w-5" />
                    </div>
                    <div>
                      <CardTitle className="text-lg">流程工作栏</CardTitle>
                      <div className="text-sm text-muted-foreground">同一视口内整合任务时间线、reason console 与任务中心跳转。</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button asChild type="button" variant="outline" size="sm" className="rounded-full">
                      <Link to="/tasks">
                        <SquareArrowOutUpRight className="h-3.5 w-3.5" />
                        任务中心
                      </Link>
                    </Button>
                    <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={() => setWorkflowOpen((value) => !value)}>
                      <ChevronDown className={`h-4 w-4 transition-transform ${workflowOpen ? '' : '-rotate-90'}`} />
                    </Button>
                  </div>
                </div>
              </CardHeader>
              <Collapsible open={workflowOpen} onOpenChange={setWorkflowOpen}>
                <CollapsibleContent>
                  <CardContent className="space-y-4 p-4 lg:p-6">
                    <TaskProgressHeader taskId={currentTaskId || activeSessionId || undefined} />
                    {taskStatus === 'failed' && !isSessionRunning && taskErrorInfo.display ? (
                      <div className="rounded-[20px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                        <div>{taskErrorInfo.display}</div>
                        {taskErrorInfo.code ? (
                          <code className="mt-2 block w-fit rounded-full border border-destructive/20 bg-destructive/10 px-3 py-1 font-mono text-xs text-destructive/90">
                            {taskErrorInfo.code}
                          </code>
                        ) : null}
                      </div>
                    ) : null}

                    <div className="grid gap-4 2xl:grid-cols-[minmax(280px,0.95fr)_minmax(360px,1.25fr)]">
                      <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium">任务时间线</div>
                            <div className="mt-1 text-sm text-muted-foreground">{stage || statusLabel(effectiveTaskStatus || sessionStatus || '')}</div>
                          </div>
                          <Badge variant="outline" className="rounded-full">
                            进度 {Math.round(progress)}%
                          </Badge>
                        </div>
                        <ScrollArea className="h-[240px] pr-3">
                          <TaskTimeline steps={workflowSteps} />
                        </ScrollArea>
                      </div>

                      <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
                        <div className="mb-3 flex items-center justify-between gap-3">
                          <div>
                            <div className="text-sm font-medium">Reason Console</div>
                            <div className="mt-1 text-sm text-muted-foreground">明确区分原始 reasoning 与 trace 降级态。</div>
                          </div>
                          <Badge variant="outline" className="rounded-full">
                            {reasonEntries.length} 条
                          </Badge>
                        </div>
                        <ScrollArea className="h-[240px] pr-3">
                          {reasonEntries.length === 0 ? (
                            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">当前还没有 reasoning 片段。</div>
                          ) : (
                            <div className="space-y-3">
                              {reasonEntries.map((entry) => (
                                <div key={entry.id} className="rounded-[18px] border border-border/70 bg-background/70 p-3">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <Badge variant="outline" className="rounded-full">
                                      {entry.label}
                                    </Badge>
                                    <Badge variant="outline" className="rounded-full">
                                      {entry.stageLabel}
                                    </Badge>
                                  </div>
                                  <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/90">{entry.content}</div>
                                </div>
                              ))}
                            </div>
                          )}
                        </ScrollArea>
                      </div>
                    </div>
                  </CardContent>
                </CollapsibleContent>
              </Collapsible>
            </Card>
            <Card className="overflow-hidden rounded-[30px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.98),rgba(247,242,232,0.92))] shadow-[0_22px_60px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(24,26,40,0.96),rgba(16,18,28,0.95))] dark:shadow-[0_24px_80px_rgba(0,0,0,0.56)]">
              <CardHeader className="border-b border-border/60 pb-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <CardTitle className="text-lg">Draft Stream</CardTitle>
                    <div className="mt-1 text-sm text-muted-foreground">恢复会话后可继续看见草稿、审查状态和局部重生成结果。</div>
                  </div>
                  {isGenerating ? (
                    <div className="inline-flex items-center gap-2 rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700 dark:border-sky-800/70 dark:bg-sky-950/45 dark:text-sky-200">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      生成中
                    </div>
                  ) : null}
                </div>
              </CardHeader>
              <CardContent className="h-[720px] p-4 lg:p-6">
                {session ? (
                  <GenerationStream
                    sessionId={session.sessionId}
                    drafts={session.drafts}
                    getDraftRef={(index) => (node) => {
                      draftRefs.current[index] = node
                    }}
                    onConfirm={handleConfirmDraft}
                    onRegenerateSection={handleRegenerateSection}
                    onSectionChange={handleSectionChange}
                    onToggleSectionLock={handleToggleSectionLock}
                  />
                ) : sessionDetailQuery.isFetching ? (
                  <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-border bg-background/60 px-6 text-center">
                    <div className="max-w-xl space-y-3">
                      <Loader2 className="mx-auto h-6 w-6 animate-spin text-muted-foreground" />
                      <div className="text-sm text-muted-foreground">正在加载会话草稿…</div>
                    </div>
                  </div>
                ) : (
                  <div className="flex h-full items-center justify-center rounded-[28px] border border-dashed border-border bg-background/60 px-6 text-center">
                    <div className="max-w-xl space-y-3">
                      <div className="text-xl font-semibold">透明工作台已就绪</div>
                      <div className="text-sm leading-6 text-muted-foreground">
                        左侧恢复历史会话，中间查看流程与题目流，右侧配置知识点树。底部对话式输入区会沿用当前选择继续出题。
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>

            <MissionComposer
              missionText={missionText}
              subject={lib.filters.subject}
              count={count}
              difficulty={difficulty}
              questionType={questionType}
              useStudyArchive={useStudyArchive}
              useReferenceQuestions={useReferenceQuestions}
              referenceSource={referenceSource}
              referenceYearRange={referenceYearRange}
              mode={mode}
              subjects={(subjects || []).filter((item) => String(item.code || '').trim())}
              isGenerating={isGenerating}
              primaryActionLabel={primaryActionLabel}
              canStop={Boolean(
                (mode === 'infinite' || session?.mode === 'infinite') &&
                (autoAppendEnabled || isStopping || session?.stopRequested || isGenerating)
              )}
              selectedKnowledgeCount={selectedKnowledgePointIds.length}
              onMissionTextChange={setMissionText}
              onSubjectChange={lib.setSubject}
              onCountChange={setCount}
              onDifficultyChange={setDifficulty}
              onQuestionTypeChange={setQuestionType}
              onUseStudyArchiveChange={setUseStudyArchive}
              onUseReferenceQuestionsChange={setUseReferenceQuestions}
              onReferenceSourceChange={(value) => setReferenceSource(value as 'any' | 'gaokao' | 'mock' | 'joint')}
              onReferenceYearRangeChange={(value) => setReferenceYearRange(value as 'all' | '3' | '5')}
              onModeChange={setMode}
              onGenerate={startGeneration}
              onStop={handleStop}
            />
          </div>

          <div className="xl:col-span-2 2xl:col-auto">
            <ContextRail
              subject={lib.filters.subject}
              mode={mode}
              sessionStatus={statusLabel(session?.status || '')}
              gradeId={gradeId}
              textbookVersionId={textbookVersionId}
              grades={subjectFilters.grades || []}
              textbookVersions={subjectFilters.textbookVersions || []}
              knowledgeTree={knowledgeTree}
              isKnowledgeLoading={knowledgeTreeQuery.isFetching}
              knowledgeError={knowledgeTreeQuery.error instanceof Error ? knowledgeTreeQuery.error.message : undefined}
              selectedKnowledgeIds={selectedKnowledgePointIds}
              selectedKnowledgeLabels={selectedKnowledgeNodeLabels}
              libraryTotal={lib.total}
              onGradeChange={setGradeId}
              onTextbookVersionChange={setTextbookVersionId}
              onToggleKnowledgePoint={handleToggleKnowledgePoint}
              onClearKnowledgePoints={() => {
                setSelectedKnowledgePointIds([])
                setSelectedKnowledgePointLabels([])
              }}
            />
          </div>
        </div>

        <Separator className="opacity-60" />

        <ConfirmedShelf
          drafts={confirmedDrafts}
          status={session?.status}
          isCommitting={isCommitting}
          isDiscarding={isDiscarding}
          onRemove={handleConfirmDraft}
          onCommit={handleCommit}
          onDiscard={handleDiscard}
        />
      </div>
    </div>
  )
}
