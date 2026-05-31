import { useMemo, useState } from 'react'
import { bulkDeleteQuestionLibraryItems } from '@/api/questionLibrary'
import type { useQuestionLibrary } from '@/features/generation/questionLibrary/hooks/useQuestionLibrary'
import { readString } from '@/lib/record'

interface UseAiGenerateBulkSelectionOptions {
  lib: ReturnType<typeof useQuestionLibrary>
  onCloseDetail: () => void
}

export function useAiGenerateBulkSelection({ lib, onCloseDetail }: UseAiGenerateBulkSelectionOptions) {
  const [bulkMode, setBulkMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Record<string, boolean>>({})
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [bulkError, setBulkError] = useState<string | null>(null)

  const selectedCount = useMemo(() => {
    return Object.values(selectedIds).filter(Boolean).length
  }, [selectedIds])

  const toggleBulkMode = () => {
    setBulkError(null)
    setSelectedIds({})
    setBulkMode((v) => !v)
  }

  const toggleSelected = (qid: string) => {
    const id = String(qid || '').trim()
    if (!id) return
    setSelectedIds((prev) => {
      const next = { ...prev }
      if (next[id]) delete next[id]
      else next[id] = true
      return next
    })
  }

  const selectAllOnPage = () => {
    setBulkError(null)
    setSelectedIds(() => {
      const next: Record<string, boolean> = {}
      for (const it of lib.items) {
        const id = String(it.question_id || '').trim()
        if (!id) continue
        next[id] = true
      }
      return next
    })
  }

  const clearSelection = () => {
    setBulkError(null)
    setSelectedIds({})
  }

  const deleteSelected = async () => {
    if (isBulkDeleting) return
    const ids = Object.entries(selectedIds)
      .filter(([, v]) => v)
      .map(([k]) => k)
    if (ids.length === 0) return

    const ok = confirm(`确定要删除选中的 ${ids.length} 道题吗？此操作不可恢复。`)
    if (!ok) return

    setIsBulkDeleting(true)
    setBulkError(null)
    try {
      await bulkDeleteQuestionLibraryItems(ids)
      const deletedSet = new Set(ids)
      if (deletedSet.has(String(lib.selectedId || '').trim())) {
        lib.setSelectedId('')
        onCloseDetail()
      }
      clearSelection()
      await lib.refreshList()
      await lib.refreshDetail()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : readString(err, 'message')
      setBulkError(msg || '批量删除失败')
    } finally {
      setIsBulkDeleting(false)
    }
  }

  return {
    bulkMode,
    selectedIds,
    selectedCount,
    isBulkDeleting,
    bulkError,
    toggleBulkMode,
    toggleSelected,
    selectAllOnPage,
    clearSelection,
    deleteSelected,
  }
}
