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
  sort: 'updated_at' | 'ai_score'
  order: 'desc' | 'asc'
}

export function useQuestionLibrary() {
  const queryClient = useQueryClient()

  const [filters, setFilters] = useState<QuestionLibraryFilters>({
    subject: '高中数学',
    origin: 'all',
    hidden: '0',
    q: '',
    sort: 'updated_at',
    order: 'desc',
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
  const setSort = (sort: 'updated_at' | 'ai_score') => setFilters((prev) => ({ ...prev, sort }))
  const setOrder = (order: 'desc' | 'asc') => setFilters((prev) => ({ ...prev, order }))

  return {
    filters,
    setSubject,
    setOrigin,
    setHidden,
    setQuery,
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

