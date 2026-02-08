import { apiClient } from './client'

export interface CanvasBoard {
  id: string
  name: string
  data: unknown
  createdAt: string
  updatedAt: string
}

// Get all canvas boards
export async function getCanvasBoards(): Promise<CanvasBoard[]> {
  const response = await apiClient.get<CanvasBoard[]>('/canvas/boards')
  return response.data
}

// Get a single canvas board
export async function getCanvasBoard(id: string): Promise<CanvasBoard> {
  const response = await apiClient.get<CanvasBoard>(`/canvas/boards/${id}`)
  return response.data
}

// Create a new canvas board
export async function createCanvasBoard(data: {
  name: string
  data?: unknown
}): Promise<CanvasBoard> {
  const response = await apiClient.post<CanvasBoard>('/canvas/boards', data)
  return response.data
}

// Update a canvas board
export async function updateCanvasBoard(
  id: string,
  data: Partial<CanvasBoard>
): Promise<CanvasBoard> {
  const response = await apiClient.patch<CanvasBoard>(`/canvas/boards/${id}`, data)
  return response.data
}

// Delete a canvas board
export async function deleteCanvasBoard(id: string): Promise<void> {
  await apiClient.delete(`/canvas/boards/${id}`)
}
