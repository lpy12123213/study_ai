import { useQuery } from '@tanstack/react-query'
import * as subjectsApi from '@/api/subjects'

export function useSubjects() {
  return useQuery({
    queryKey: ['subjects'],
    queryFn: subjectsApi.getSubjects,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
  })
}

export function useSubjectFilters(subjectCode: string | undefined) {
  return useQuery({
    queryKey: ['subjectFilters', subjectCode],
    queryFn: () => subjectsApi.getSubjectFilters(subjectCode!),
    enabled: !!subjectCode,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
  })
}

export function useSubjectKnowledgeTree(
  subjectCode: string | undefined,
  params?: { gradeId?: string; textbookVersionId?: string }
) {
  return useQuery({
    queryKey: ['subjectKnowledgeTree', subjectCode, params?.gradeId || '', params?.textbookVersionId || ''],
    queryFn: () => subjectsApi.getSubjectKnowledgeTree(subjectCode!, params),
    enabled: !!subjectCode,
    staleTime: 10 * 60 * 1000,
    gcTime: 30 * 60 * 1000,
    retry: 1,
  })
}
