import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getQuestionLibraryItem,
  listQuestionLibrary,
  type QuestionLibraryDetailResponse,
  type QuestionLibraryListItem,
  type QuestionOrigin,
} from '@/api/questionLibrary'

export interface QuestionLibraryFilters {
  subject: string
  origin: QuestionOrigin | 'all'
  hidden: '0' | '1' | 'all'
  q: string
  examScene: string
  questionType: string
  difficulty: string
  category: string
  year: string
  region: string
  grade: string
  semester: string
  method: string
  onlyNew: boolean
  sort: 'updated_at' | 'ai_score'
  order: 'desc' | 'asc'
}

export function useQuestionLibrary(options?: {
  initialFilters?: Partial<QuestionLibraryFilters>
}) {
  const queryClient = useQueryClient()

  const [filters, setFilters] = useState<QuestionLibraryFilters>(() => {
    const initial = (options?.initialFilters || {}) as Partial<QuestionLibraryFilters>
    return {
      subject: typeof initial.subject === 'string' ? initial.subject : '',
      origin: initial.origin ?? 'all',
      hidden: initial.hidden ?? '0',
      q: typeof initial.q === 'string' ? initial.q : '',
      examScene: typeof initial.examScene === 'string' ? initial.examScene : '',
      questionType: typeof initial.questionType === 'string' ? initial.questionType : '',
      difficulty: typeof initial.difficulty === 'string' ? initial.difficulty : '',
      category: typeof initial.category === 'string' ? initial.category : '',
      year: typeof initial.year === 'string' ? initial.year : '',
      region: typeof initial.region === 'string' ? initial.region : '',
      grade: typeof initial.grade === 'string' ? initial.grade : '',
      semester: typeof initial.semester === 'string' ? initial.semester : '',
      method: typeof initial.method === 'string' ? initial.method : '',
      onlyNew: typeof initial.onlyNew === 'boolean' ? initial.onlyNew : false,
      sort: initial.sort ?? 'updated_at',
      order: initial.order ?? 'desc',
    }
  })

  const [selectedId, setSelectedId] = useState<string>('')

  const listQuery = useQuery({
    queryKey: ['questionLibrary', filters],
    queryFn: () =>
      listQuestionLibrary({
        subject: filters.subject,
        origin: filters.origin === 'all' ? undefined : filters.origin,
        hidden: filters.hidden,
        q: filters.q.trim() ? filters.q.trim() : undefined,
        exam_scene: filters.examScene.trim() ? filters.examScene.trim() : undefined,
        question_type: filters.questionType.trim() ? filters.questionType.trim() : undefined,
        difficulty: filters.difficulty.trim() ? filters.difficulty.trim() : undefined,
        category: filters.category.trim() ? filters.category.trim() : undefined,
        year: filters.year.trim() ? filters.year.trim() : undefined,
        region: filters.region.trim() ? filters.region.trim() : undefined,
        grade: filters.grade.trim() ? filters.grade.trim() : undefined,
        semester: filters.semester.trim() ? filters.semester.trim() : undefined,
        method: filters.method.trim() ? filters.method.trim() : undefined,
        only_new: filters.onlyNew || undefined,
        sort: filters.sort,
        order: filters.order,
        limit: 80,
        offset: 0,
      }),
    enabled: !!filters.subject,
  })

  const items = (listQuery.data?.items || []) as QuestionLibraryListItem[]
  const total = listQuery.data?.total || 0

  const selectedItem = useMemo(() => {
    const id = selectedId.trim()
    if (!id) return null
    return items.find((it) => String(it.question_id || '').trim() === id) || null
  }, [items, selectedId])

  const detailQuery = useQuery({
    queryKey: ['questionLibraryDetail', selectedId],
    queryFn: () => getQuestionLibraryItem(selectedId),
    enabled: !!selectedId.trim(),
  })

  const detail = (detailQuery.data || null) as QuestionLibraryDetailResponse | null

  const refreshList = async () => {
    await queryClient.invalidateQueries({ queryKey: ['questionLibrary'] })
  }

  const refreshDetail = async () => {
    const id = selectedId.trim()
    if (!id) return
    await queryClient.invalidateQueries({ queryKey: ['questionLibraryDetail', id] })
  }

  const setSubject = (subject: string) => setFilters((prev) => ({ ...prev, subject }))
  const setOrigin = (origin: QuestionOrigin | 'all') => setFilters((prev) => ({ ...prev, origin }))
  const setHidden = (hidden: '0' | '1' | 'all') => setFilters((prev) => ({ ...prev, hidden }))
  const setQuery = (q: string) => setFilters((prev) => ({ ...prev, q }))
  const setExamScene = (examScene: string) => setFilters((prev) => ({ ...prev, examScene }))
  const setQuestionType = (questionType: string) => setFilters((prev) => ({ ...prev, questionType }))
  const setDifficulty = (difficulty: string) => setFilters((prev) => ({ ...prev, difficulty }))
  const setCategory = (category: string) => setFilters((prev) => ({ ...prev, category }))
  const setMoreFilter = (key: 'year' | 'region' | 'grade' | 'semester' | 'method', value: string) =>
    setFilters((prev) => ({ ...prev, [key]: value }))
  const setOnlyNew = (onlyNew: boolean) => setFilters((prev) => ({ ...prev, onlyNew }))
  const setSort = (sort: 'updated_at' | 'ai_score') => setFilters((prev) => ({ ...prev, sort }))
  const setOrder = (order: 'desc' | 'asc') => setFilters((prev) => ({ ...prev, order }))

  return {
    filters,
    setSubject,
    setOrigin,
    setHidden,
    setQuery,
    setExamScene,
    setQuestionType,
    setDifficulty,
    setCategory,
    setMoreFilter,
    setOnlyNew,
    setSort,
    setOrder,

    listQuery,
    items,
    total,

    selectedId,
    setSelectedId,
    selectedItem,

    detailQuery,
    detail,

    refreshList,
    refreshDetail,
  }
}

