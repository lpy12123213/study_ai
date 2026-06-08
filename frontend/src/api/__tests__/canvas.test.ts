import { describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/api/client'
import {
  createCanvasBoard,
  getCanvasBoards,
  updateCanvasBoard,
  type CanvasSnapshot,
} from '@/api/canvas'

vi.mock('@/api/client', () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
  },
}))

describe('canvas api', () => {
  it('unwraps board lists from the backend success envelope', async () => {
    vi.mocked(apiClient.get).mockResolvedValueOnce({
      data: {
        success: true,
        boards: [{ id: 1, title: '错题画布', subject: '高中数学', revision: 3, created_at: 'c', updated_at: 'u' }],
      },
    })

    const boards = await getCanvasBoards({ q: '函数', limit: 10 })

    expect(apiClient.get).toHaveBeenCalledWith('/canvas/boards', { params: { q: '函数', limit: 10 } })
    expect(boards[0]).toEqual({
      id: 1,
      title: '错题画布',
      subject: '高中数学',
      revision: 3,
      createdAt: 'c',
      updatedAt: 'u',
    })
  })

  it('creates boards with title/subject/snapshot and unwraps the board', async () => {
    const snapshot: CanvasSnapshot = { version: 1, nodes: [] }
    vi.mocked(apiClient.post).mockResolvedValueOnce({
      data: { success: true, board: { id: 2, title: '新画布', subject: '物理', revision: 1, snapshot } },
    })

    const board = await createCanvasBoard({ title: '新画布', subject: '物理', snapshot })

    expect(apiClient.post).toHaveBeenCalledWith('/canvas/boards', { title: '新画布', subject: '物理', snapshot })
    expect(board.id).toBe(2)
    expect(board.snapshot).toEqual(snapshot)
  })

  it('uses PUT with expected_revision and returns conflict envelopes without throwing', async () => {
    const snapshot: CanvasSnapshot = { version: 1, nodes: [] }
    vi.mocked(apiClient.put).mockResolvedValueOnce({
      data: {
        success: false,
        conflict: true,
        server_board: { id: 1, title: '服务端', subject: '', revision: 5, snapshot },
      },
    })

    const result = await updateCanvasBoard(1, { expectedRevision: 4, snapshot })

    expect(apiClient.put).toHaveBeenCalledWith('/canvas/boards/1', {
      expected_revision: 4,
      snapshot,
    })
    expect(result.conflict).toBe(true)
    if (!result.success) {
      expect(result.serverBoard.revision).toBe(5)
    }
  })
})
