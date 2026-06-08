import { useQuery } from '@tanstack/react-query'
import { getInsightsOverview, type InsightsParams } from '@/api/insights'

export function useInsights(params: InsightsParams) {
  return useQuery({
    queryKey: ['insights', 'overview', params],
    queryFn: () => getInsightsOverview(params),
  })
}
