import { useQuery } from '@tanstack/react-query'
import { getMastery } from '@/api/wrongbook'

export function useMastery(subject?: string) {
  const normalizedSubject = subject?.trim() || undefined
  return useQuery({
    queryKey: ['wrongbook', 'mastery', normalizedSubject || 'all'],
    queryFn: () => getMastery({ subject: normalizedSubject }),
  })
}
