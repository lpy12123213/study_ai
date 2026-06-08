import { useQuery } from '@tanstack/react-query'
import { getReviewQueue } from '@/api/wrongbook'

export function useReviewQueue(subject?: string) {
  const normalizedSubject = subject?.trim() || undefined
  return useQuery({
    queryKey: ['wrongbook', 'review', normalizedSubject || 'all'],
    queryFn: () => getReviewQueue({ subject: normalizedSubject, limit: 50 }),
  })
}
