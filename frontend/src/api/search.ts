import { apiClient } from '@/api/client'

export type SearchResult =
  | {
      type: 'conversation'
      title: string
      snippet: string
      conversation_id: number
      message_id: number
      score?: number
    }
  | {
      type: 'paper'
      title: string
      snippet: string
      paper_id: number
      question_id: string
      score?: number
    }
  | {
      type: 'study_archive'
      title: string
      snippet: string
      archive_id: number
      score?: number
    }
  | {
      type: string
      title?: string
      snippet?: string
      [key: string]: any
    }

export type SearchResponse = {
  query: string
  results: SearchResult[]
  count: number
}

export async function searchAll(params: {
  q: string
  types?: string[]
  limit?: number
}): Promise<SearchResponse> {
  const response = await apiClient.get<SearchResponse>('/search', {
    params: {
      q: params.q,
      limit: params.limit ?? 50,
      types: params.types?.join(','),
    },
  })
  return response.data
}

export const searchApi = {
  searchAll,
  search: async (params: { q: string; types?: string[]; limit?: number }): Promise<{ data: any }> => ({
    data: await searchAll(params),
  }),
}
