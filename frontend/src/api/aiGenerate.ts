import { apiClient } from './instance'

export const aiGenerateApi = {
  list: (params?: object) => apiClient.get('/ai-generate', { params }),
  getSession: (id: string) => apiClient.get(`/ai-generate/${id}`),
  getQuestion: (sessionId: string, questionId: string) =>
    apiClient.get(`/ai-generate/${sessionId}/questions/${questionId}`),
  updateQuestion: (sessionId: string, questionId: string, data: object) =>
    apiClient.put(`/ai-generate/${sessionId}/questions/${questionId}`, data),
}
