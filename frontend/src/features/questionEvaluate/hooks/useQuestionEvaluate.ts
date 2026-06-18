import { useEffect, useMemo, useRef, useState } from 'react'
import { useSubjects } from '@/hooks/useSubjects'
import * as questionEvaluateApi from '@/api/questionEvaluate'
import { DIFFICULTY_ANY } from '../utils'

export type QuestionEvaluatePageState = {
  // subjects
  subjects: ReturnType<typeof useSubjects>['data']
  subject: string
  setSubject: (value: string) => void
  // search
  query: string
  setQuery: (value: string) => void
  difficulty: string
  setDifficulty: (value: string) => void
  isSearching: boolean
  searchError: string | null
  searchResults: questionEvaluateApi.QuestionEvaluateQuestion[]
  // selection
  selectedIds: Record<string, boolean>
  selectedQuestions: questionEvaluateApi.QuestionEvaluateQuestion[]
  toggleSelected: (id: string) => void
  selectAll: () => void
  clearSelection: () => void
  // evaluate
  requirements: string
  setRequirements: (value: string) => void
  isEvaluating: boolean
  evalError: string | null
  evalResults: questionEvaluateApi.QuestionEvaluateResult[]
  orderedEval: questionEvaluateApi.QuestionEvaluateResult[]
  evaluateStats: Array<{ label: string; value: string }>
  // handlers
  doSearch: () => Promise<void>
  doEvaluate: () => Promise<void>
}

export function useQuestionEvaluate(): QuestionEvaluatePageState {
  const { data: subjects } = useSubjects()

  const [subject, setSubject] = useState<string>('高中数学')
  const [query, setQuery] = useState<string>('')
  const [difficulty, setDifficulty] = useState<string>(DIFFICULTY_ANY)

  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState<string | null>(null)
  const [searchResults, setSearchResults] = useState<questionEvaluateApi.QuestionEvaluateQuestion[]>([])

  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({})

  const [requirements, setRequirements] = useState<string>('')
  const [isEvaluating, setIsEvaluating] = useState(false)
  const [evalError, setEvalError] = useState<string | null>(null)
  const [evalResults, setEvalResults] = useState<questionEvaluateApi.QuestionEvaluateResult[]>([])
  const evaluateAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      evaluateAbortRef.current?.abort()
    }
  }, [])

  const selectedQuestions = useMemo(() => {
    const set = new Set(Object.entries(selectedIds).filter(([, v]) => v).map(([k]) => k))
    return searchResults.filter((q) => set.has(q.questionId))
  }, [searchResults, selectedIds])

  const toggleSelected = (id: string) => {
    setSelectedIds((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const selectAll = () => {
    const next: Record<string, boolean> = {}
    for (const q of searchResults) next[q.questionId] = true
    setSelectedIds(next)
  }

  const clearSelection = () => {
    setSelectedIds({})
  }

  const doSearch = async () => {
    const q = query.trim()
    if (!q) return

    setIsSearching(true)
    setSearchError(null)
    setEvalResults([])
    setEvalError(null)

    try {
      const res = await questionEvaluateApi.searchQuestions({
        query: q,
        subject,
        difficulty: difficulty && difficulty !== DIFFICULTY_ANY ? difficulty : undefined,
        limit: 20,
        maxPages: 2,
        minQualityScore: 0,
      })

      if (!res.success) {
        setSearchError(res.error || '搜索失败')
        setSearchResults([])
        setSelectedIds({})
        return
      }

      setSearchResults(res.questions)
      setSelectedIds({})
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err || '')
      setSearchError(msg || '搜索失败')
      setSearchResults([])
      setSelectedIds({})
    } finally {
      setIsSearching(false)
    }
  }

  const doEvaluate = async () => {
    if (selectedQuestions.length === 0) return

    setIsEvaluating(true)
    setEvalError(null)
    evaluateAbortRef.current?.abort()
    const controller = new AbortController()
    evaluateAbortRef.current = controller
    try {
      const res = await questionEvaluateApi.evaluateQuestions({
        subject,
        requirements,
        questions: selectedQuestions,
      }, { signal: controller.signal })
      if (controller.signal.aborted) return
      setEvalResults(res.results)
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const msg = err instanceof Error ? err.message : String(err || '')
      setEvalError(msg || '鉴别失败')
      setEvalResults([])
    } finally {
      if (evaluateAbortRef.current === controller) {
        evaluateAbortRef.current = null
        setIsEvaluating(false)
      }
    }
  }

  const orderedEval = useMemo(() => {
    const items = [...evalResults]
    items.sort((a, b) => (b.overallScore || 0) - (a.overallScore || 0))
    return items
  }, [evalResults])

  const evaluateStats = [
    { label: '搜索结果', value: `${searchResults.length}` },
    { label: '已选题目', value: `${selectedQuestions.length}` },
    { label: '鉴别结果', value: `${evalResults.length}` },
    { label: '学科', value: subject || '未选择' },
  ]

  return {
    subjects,
    subject,
    setSubject,
    query,
    setQuery,
    difficulty,
    setDifficulty,
    isSearching,
    searchError,
    searchResults,
    selectedIds,
    selectedQuestions,
    toggleSelected,
    selectAll,
    clearSelection,
    requirements,
    setRequirements,
    isEvaluating,
    evalError,
    evalResults,
    orderedEval,
    evaluateStats,
    doSearch,
    doEvaluate,
  }
}
