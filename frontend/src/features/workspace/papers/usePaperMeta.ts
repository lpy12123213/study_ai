import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as metaApi from '@/api/meta'

export function usePaperMeta() {
  const queryClient = useQueryClient()
  const { data } = useQuery({
    queryKey: ['itemMeta', 'paper'],
    queryFn: () => metaApi.listMeta({ itemType: 'paper', limit: 500 }),
  })

  const items: metaApi.ItemMeta[] = useMemo(() => data?.items ?? [], [data])

  const byId = useMemo(() => {
    const m = new Map<string, metaApi.ItemMeta>()
    for (const row of items) {
      m.set(String(row.item_id), row)
    }
    return m
  }, [items])

  const tagOptions = useMemo(() => {
    const set = new Set<string>()
    for (const row of items) {
      const tags = Array.isArray(row.tags) ? row.tags : []
      for (const t of tags) {
        const v = String(t || '').trim()
        if (v) set.add(v)
      }
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b))
  }, [items])

  const updateMeta = useMutation({
    mutationFn: (args: { itemId: string; patch: { starred?: boolean; pinned?: boolean; tags?: string[] } }) =>
      metaApi.setMeta('paper', args.itemId, args.patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['itemMeta', 'paper'] })
    },
  })

  return { byId, tagOptions, updateMeta }
}
