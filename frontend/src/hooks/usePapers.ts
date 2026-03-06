import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import * as papersApi from '@/api/papers'
import type { CreatePaperRequest, GetPaperOptions, GetPapersParams } from '@/api/papers'

export function usePapers(params: GetPapersParams = {}) {
  return useQuery({
    queryKey: ['papers', params],
    queryFn: () => papersApi.getPapers(params),
  })
}

export function usePaper(id: string | undefined, options: GetPaperOptions & { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['paper', id, Boolean(options.includeAnalysis)],
    queryFn: () => papersApi.getPaper(id!, { includeAnalysis: options.includeAnalysis }),
    enabled: !!id && (options.enabled ?? true),
  })
}

export function useCreatePaper() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (data: CreatePaperRequest) => papersApi.createPaper(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['papers'] })
    },
  })
}

export function useDeletePaper() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: papersApi.deletePaper,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['papers'] })
    },
  })
}

export function usePaperDownloadLink() {
  return useMutation({
    mutationFn: papersApi.getPaperDownloadLink,
  })
}

export function usePaperExport() {
  return useMutation({
    mutationFn: ({ id, req }: { id: string; req: papersApi.PaperExportRequest }) =>
      papersApi.exportPaper(id, req),
  })
}
