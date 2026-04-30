import { apiClient } from './instance'

export const blueprintsApi = {
  list: (params?: object) => apiClient.get('/blueprints', { params }),
  get: (id: string) => apiClient.get(`/blueprints/${id}`),
  create: (data: object) => apiClient.post('/blueprints', data),
  update: (id: string, data: object) => apiClient.put(`/blueprints/${id}`, data),
  delete: (id: string) => apiClient.delete(`/blueprints/${id}`),
}
