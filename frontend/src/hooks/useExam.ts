import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as examApi from '@/api/exam'
import type { SaveExamAnswerRequest, StartExamRequest } from '@/types/exam'

export function useExamSession(sessionId: string | undefined, options: { enabled?: boolean; includeAnswers?: boolean } = {}) {
  return useQuery({
    queryKey: ['examSession', sessionId, Boolean(options.includeAnswers)],
    queryFn: () => examApi.getExamSession(sessionId!, { includeAnswers: options.includeAnswers }),
    enabled: Boolean(sessionId) && (options.enabled ?? true),
    refetchInterval: (query) => (query.state.data?.status === 'in_progress' ? 30_000 : false),
  })
}

export function useExamSessions(params: { paperId?: number; limit?: number } = {}) {
  return useQuery({
    queryKey: ['examSessions', params],
    queryFn: () => examApi.getExamSessions(params),
  })
}

export function useExamResult(sessionId: string | undefined, options: { enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ['examResult', sessionId],
    queryFn: () => examApi.getExamResult(sessionId!),
    enabled: Boolean(sessionId) && (options.enabled ?? true),
  })
}

export function useStartExam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (request: StartExamRequest) => examApi.startExam(request),
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['examSessions'] })
      queryClient.setQueryData(['examSession', session.sessionId], session)
    },
  })
}

export function useSaveAnswer(sessionId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (answer: SaveExamAnswerRequest) => examApi.saveAnswer(sessionId!, answer),
    onSuccess: () => {
      if (sessionId) queryClient.invalidateQueries({ queryKey: ['examSession', sessionId] })
    },
  })
}

export function useBatchSaveAnswers(sessionId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (answers: SaveExamAnswerRequest[]) => examApi.batchSaveAnswers(sessionId!, answers),
    onSuccess: () => {
      if (sessionId) queryClient.invalidateQueries({ queryKey: ['examSession', sessionId] })
    },
  })
}

export function useUploadHandwriting(sessionId: string | undefined) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ questionId, file }: { questionId: string; file: File }) =>
      examApi.uploadHandwriting(sessionId!, questionId, file),
    onSuccess: () => {
      if (sessionId) queryClient.invalidateQueries({ queryKey: ['examSession', sessionId] })
    },
  })
}

export function useSubmitExam() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => examApi.submitExam(sessionId),
    onSuccess: (result, sessionId) => {
      queryClient.invalidateQueries({ queryKey: ['examSession', sessionId] })
      queryClient.setQueryData(['examResult', sessionId], result)
      queryClient.invalidateQueries({ queryKey: ['examSessions'] })
    },
  })
}
