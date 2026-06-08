import { create } from 'zustand'
import { generateId } from '@/lib/utils'
import type { CanvasBoard, CanvasNode, CanvasNoteNode, CanvasQuestionNode, CanvasSnapshot, PickedCanvasQuestion } from '@/api/canvas'

type NodePosition = { x: number; y: number }

interface CanvasStoreState {
  boardId: number | null
  title: string
  subject: string
  revision: number
  nodes: CanvasNode[]
  dirty: boolean
  loadBoard: (board: CanvasBoard) => void
  applySavedBoard: (board: CanvasBoard) => void
  applyServerBoard: (board: CanvasBoard) => void
  setTitle: (title: string) => void
  setSubject: (subject: string) => void
  addNote: (input?: Partial<CanvasNoteNode>) => CanvasNoteNode
  addQuestions: (questions: PickedCanvasQuestion[]) => void
  moveNode: (nodeId: string, position: NodePosition) => void
  resizeNode: (nodeId: string, size: { w: number; h: number }) => void
  updateNote: (nodeId: string, text: string) => void
  removeNode: (nodeId: string) => void
  snapshot: () => CanvasSnapshot
  reset: () => void
}

const initialState = {
  boardId: null,
  title: '',
  subject: '',
  revision: 0,
  nodes: [] as CanvasNode[],
  dirty: false,
}

function cloneNodes(nodes: CanvasNode[] | undefined): CanvasNode[] {
  return (nodes || []).map((node) => ({ ...node }))
}

function clampSize(value: number, fallback: number): number {
  const next = Number(value)
  return Number.isFinite(next) ? Math.max(120, next) : fallback
}

function noteFromInput(input: Partial<CanvasNoteNode> = {}): CanvasNoteNode {
  return {
    id: input.id || generateId('note-'),
    kind: 'note',
    x: Number.isFinite(input.x) ? Number(input.x) : 80,
    y: Number.isFinite(input.y) ? Number(input.y) : 80,
    w: clampSize(Number(input.w), 260),
    h: clampSize(Number(input.h), 160),
    text: input.text || '',
  }
}

function questionNodeFromPicked(question: PickedCanvasQuestion, index: number): CanvasQuestionNode {
  return {
    id: generateId('question-'),
    kind: 'question',
    x: 80 + (index % 3) * 360,
    y: 100 + Math.floor(index / 3) * 260,
    w: 340,
    h: 240,
    questionId: question.questionId,
    title: question.title || `题目 ${question.questionId}`,
    stemHtml: question.stemHtml,
    meta: question.meta,
    type: question.type,
    difficulty: question.difficulty,
    knowledgePoints: question.knowledgePoints,
    source: question.source,
    url: question.url,
    selectReason: question.selectReason,
  }
}

function loadBoardState(board: CanvasBoard) {
  return {
    boardId: board.id,
    title: board.title,
    subject: board.subject || '',
    revision: board.revision,
    nodes: cloneNodes(board.snapshot?.nodes),
    dirty: false,
  }
}

export const useCanvasStore = create<CanvasStoreState>((set, get) => ({
  ...initialState,
  loadBoard: (board) => set(loadBoardState(board)),
  applySavedBoard: (board) => set(loadBoardState(board)),
  applyServerBoard: (board) => set(loadBoardState(board)),
  setTitle: (title) => set({ title, dirty: true }),
  setSubject: (subject) => set({ subject, dirty: true }),
  addNote: (input) => {
    const note = noteFromInput(input)
    set((state) => ({ nodes: [...state.nodes, note], dirty: true }))
    return note
  },
  addQuestions: (questions) => {
    const nodes = questions.map(questionNodeFromPicked)
    if (!nodes.length) return
    set((state) => ({ nodes: [...state.nodes, ...nodes], dirty: true }))
  },
  moveNode: (nodeId, position) => {
    set((state) => ({
      nodes: state.nodes.map((node) =>
        node.id === nodeId ? { ...node, x: Number(position.x), y: Number(position.y) } : node
      ),
      dirty: true,
    }))
  },
  resizeNode: (nodeId, size) => {
    set((state) => ({
      nodes: state.nodes.map((node) =>
        node.id === nodeId ? { ...node, w: clampSize(size.w, node.w), h: clampSize(size.h, node.h) } : node
      ),
      dirty: true,
    }))
  },
  updateNote: (nodeId, text) => {
    set((state) => ({
      nodes: state.nodes.map((node) => (node.id === nodeId && node.kind === 'note' ? { ...node, text } : node)),
      dirty: true,
    }))
  },
  removeNode: (nodeId) => {
    set((state) => ({ nodes: state.nodes.filter((node) => node.id !== nodeId), dirty: true }))
  },
  snapshot: () => ({ version: 1, nodes: cloneNodes(get().nodes) }),
  reset: () => set({ ...initialState }),
}))
