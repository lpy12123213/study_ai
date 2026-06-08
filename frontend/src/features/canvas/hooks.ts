import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCanvasBoard,
  createCanvasBoardVersion,
  getCanvasBoard,
  getCanvasBoards,
  getCanvasBoardVersion,
  getCanvasBoardVersions,
  pickCanvasQuestions,
  updateCanvasBoard,
  type CanvasSnapshot,
} from '@/api/canvas'

export const canvasKeys = {
  boards: ['canvas', 'boards'] as const,
  board: (id: number | string | undefined) => ['canvas', 'board', String(id || '')] as const,
  versions: (id: number | string | undefined) => ['canvas', 'board', String(id || ''), 'versions'] as const,
}

export function useCanvasBoards(params?: { q?: string; limit?: number }) {
  return useQuery({
    queryKey: [...canvasKeys.boards, params?.q || '', params?.limit || 30],
    queryFn: () => getCanvasBoards(params),
  })
}

export function useCanvasBoard(boardId: number | string | undefined) {
  return useQuery({
    queryKey: canvasKeys.board(boardId),
    queryFn: () => getCanvasBoard(boardId || ''),
    enabled: Boolean(boardId),
  })
}

export function useCreateCanvasBoard() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: createCanvasBoard,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: canvasKeys.boards })
    },
  })
}

export function useUpdateCanvasBoard(boardId: number | string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: { title?: string; subject?: string; snapshot?: CanvasSnapshot; expectedRevision?: number }) =>
      updateCanvasBoard(boardId || '', payload),
    onSuccess: (result) => {
      if (result.success) {
        queryClient.setQueryData(canvasKeys.board(boardId), result.board)
        void queryClient.invalidateQueries({ queryKey: canvasKeys.boards })
        void queryClient.invalidateQueries({ queryKey: canvasKeys.versions(boardId) })
      }
    },
  })
}

export function useCanvasVersions(boardId: number | string | undefined) {
  return useQuery({
    queryKey: canvasKeys.versions(boardId),
    queryFn: () => getCanvasBoardVersions(boardId || ''),
    enabled: Boolean(boardId),
  })
}

export function useCreateCanvasVersion(boardId: number | string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => createCanvasBoardVersion(boardId || ''),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: canvasKeys.versions(boardId) })
    },
  })
}

export function useCanvasVersion(boardId: number | string | undefined, versionId: number | string | undefined) {
  return useQuery({
    queryKey: [...canvasKeys.versions(boardId), String(versionId || '')],
    queryFn: () => getCanvasBoardVersion(boardId || '', versionId || ''),
    enabled: Boolean(boardId && versionId),
  })
}

export function usePickCanvasQuestions(boardId: number | string | undefined) {
  return useMutation({
    mutationFn: (payload: {
      requirement: string
      subject?: string
      eduLevel?: string
      count?: number
      limit?: number
      maxPages?: number
    }) => pickCanvasQuestions(boardId || '', payload),
  })
}
