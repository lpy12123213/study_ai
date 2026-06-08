import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { useCanvasStore } from '@/features/canvas/store'
import type { CanvasBoard, CanvasSnapshot } from '@/api/canvas'

function makeBoard(snapshot: CanvasSnapshot = { version: 1, nodes: [] }): CanvasBoard {
  return {
    id: 1,
    title: '学习画布',
    subject: '高中数学',
    revision: 2,
    snapshot,
    createdAt: '2026-06-08T08:00:00',
    updatedAt: '2026-06-08T08:00:00',
  }
}

describe('useCanvasStore', () => {
  beforeEach(() => {
    useCanvasStore.getState().reset()
  })

  it('loads a board snapshot and tracks node edits as dirty', () => {
    const snapshot: CanvasSnapshot = {
      version: 1,
      nodes: [{ id: 'q-1', kind: 'question', x: 10, y: 20, w: 320, h: 220, questionId: '100', title: '函数题' }],
    }
    const { result } = renderHook(() => useCanvasStore())

    act(() => result.current.loadBoard(makeBoard(snapshot)))
    expect(result.current.revision).toBe(2)
    expect(result.current.dirty).toBe(false)

    act(() => result.current.moveNode('q-1', { x: 42, y: 84 }))
    expect(result.current.nodes[0]).toMatchObject({ x: 42, y: 84 })
    expect(result.current.dirty).toBe(true)
  })

  it('marks the current snapshot clean after a successful save', () => {
    const { result } = renderHook(() => useCanvasStore())

    act(() => result.current.loadBoard(makeBoard()))
    act(() => result.current.addNote({ text: '重点整理', x: 12, y: 20 }))
    expect(result.current.dirty).toBe(true)

    act(() => result.current.applySavedBoard(makeBoard(result.current.snapshot())))

    expect(result.current.dirty).toBe(false)
    expect(result.current.revision).toBe(2)
  })

  it('can replace local edits with the conflict server board', () => {
    const { result } = renderHook(() => useCanvasStore())
    const serverSnapshot: CanvasSnapshot = {
      version: 1,
      nodes: [{ id: 'server-note', kind: 'note', x: 0, y: 0, w: 260, h: 160, text: '服务端版本' }],
    }

    act(() => result.current.loadBoard(makeBoard()))
    act(() => result.current.addNote({ text: '本地草稿', x: 12, y: 20 }))
    act(() => result.current.applyServerBoard(makeBoard(serverSnapshot)))

    expect(result.current.dirty).toBe(false)
    expect(result.current.nodes).toHaveLength(1)
    expect(result.current.nodes[0]).toMatchObject({ id: 'server-note', text: '服务端版本' })
  })
})
