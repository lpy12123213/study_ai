import { apiClient } from './instance'

export const shareApi = {
  get: (token: string) => apiClient.get(`/share-links/${token}`),
  create: (data: object) => apiClient.post('/share-links', data),
}
