import { apiClient } from './client'

export type CanvasNodeBase = {
  id: string
  x: number
  y: number
  w: number
  h: number
}

export type CanvasQuestionNode = CanvasNodeBase & {
  kind: 'question'
  questionId: string
  title: string
  stemHtml?: string
  meta?: Record<string, unknown>
  type?: string
  difficulty?: string
  knowledgePoints?: string[]
  source?: string
  url?: string
  selectReason?: string
}

export type CanvasNoteNode = CanvasNodeBase & {
  kind: 'note'
  text: string
}

export type CanvasNode = CanvasQuestionNode | CanvasNoteNode

export type CanvasSnapshot = {
  version: 1
  nodes: CanvasNode[]
}

export interface CanvasBoardSummary {
  id: number
  title: string
  subject: string
  revision: number
  createdAt: string
  updatedAt: string
}

export interface CanvasBoard extends CanvasBoardSummary {
  snapshot: CanvasSnapshot
}

export interface CanvasBoardVersion {
  id: number
  boardId: number
  revision: number
  createdAt: string
  snapshot?: CanvasSnapshot
}

export interface PickedCanvasQuestion {
  success: boolean
  questionId: string
  title: string
  meta?: Record<string, unknown>
  stemHtml: string
  type?: string
  difficulty?: string
  knowledgePoints?: string[]
  source?: string
  url?: string
  selectReason?: string
}

export type UpdateCanvasBoardResult =
  | { success: true; board: CanvasBoard; conflict?: false }
  | { success: false; conflict: true; serverBoard: CanvasBoard; error?: string }

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function defaultSnapshot(): CanvasSnapshot {
  return { version: 1, nodes: [] }
}

function toStringValue(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function toNumberValue(value: unknown, fallback = 0): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function normalizeSnapshot(value: unknown): CanvasSnapshot {
  if (!isRecord(value)) return defaultSnapshot()
  const nodes = Array.isArray(value.nodes) ? value.nodes : []
  return {
    version: 1,
    nodes: nodes.filter(isRecord).map((node) => normalizeNode(node)).filter(Boolean) as CanvasNode[],
  }
}

function normalizeNode(node: Record<string, unknown>): CanvasNode | null {
  const kind = node.kind === 'question' ? 'question' : node.kind === 'note' ? 'note' : ''
  if (!kind) return null
  const base = {
    id: toStringValue(node.id) || `${kind}-${Math.random().toString(36).slice(2, 10)}`,
    x: toNumberValue(node.x),
    y: toNumberValue(node.y),
    w: Math.max(160, toNumberValue(node.w, kind === 'question' ? 340 : 260)),
    h: Math.max(120, toNumberValue(node.h, kind === 'question' ? 240 : 160)),
  }
  if (kind === 'note') {
    return { ...base, kind, text: toStringValue(node.text) }
  }
  return {
    ...base,
    kind,
    questionId: toStringValue(node.questionId || node.question_id),
    title: toStringValue(node.title) || '题目',
    stemHtml: toStringValue(node.stemHtml || node.stem_html),
    meta: isRecord(node.meta) ? node.meta : undefined,
    type: toStringValue(node.type),
    difficulty: toStringValue(node.difficulty),
    knowledgePoints: Array.isArray(node.knowledgePoints)
      ? node.knowledgePoints.map(String)
      : Array.isArray(node.knowledge_points)
        ? node.knowledge_points.map(String)
        : undefined,
    source: toStringValue(node.source),
    url: toStringValue(node.url),
    selectReason: toStringValue(node.selectReason || node.select_reason),
  }
}

function normalizeSummary(raw: unknown): CanvasBoardSummary {
  const item = isRecord(raw) ? raw : {}
  return {
    id: toNumberValue(item.id),
    title: toStringValue(item.title) || '未命名画布',
    subject: toStringValue(item.subject),
    revision: toNumberValue(item.revision, 1),
    createdAt: toStringValue(item.createdAt || item.created_at),
    updatedAt: toStringValue(item.updatedAt || item.updated_at),
  }
}

function normalizeBoard(raw: unknown): CanvasBoard {
  const item = isRecord(raw) ? raw : {}
  return {
    ...normalizeSummary(item),
    snapshot: normalizeSnapshot(item.snapshot),
  }
}

function normalizeVersion(raw: unknown): CanvasBoardVersion {
  const item = isRecord(raw) ? raw : {}
  const version: CanvasBoardVersion = {
    id: toNumberValue(item.id),
    boardId: toNumberValue(item.boardId || item.board_id),
    revision: toNumberValue(item.revision),
    createdAt: toStringValue(item.createdAt || item.created_at),
  }
  if ('snapshot' in item) version.snapshot = normalizeSnapshot(item.snapshot)
  return version
}

function ensureSuccessEnvelope(data: unknown, key: string): Record<string, unknown> {
  if (!isRecord(data) || data.success === false) {
    const message = isRecord(data) ? toStringValue(data.error) || 'canvas_request_failed' : 'canvas_request_failed'
    throw new Error(message)
  }
  if (!(key in data)) throw new Error('canvas_response_missing_payload')
  return data
}

export async function getCanvasBoards(params?: { q?: string; limit?: number }): Promise<CanvasBoardSummary[]> {
  const response = await apiClient.get<unknown>('/canvas/boards', {
    params: {
      q: params?.q,
      limit: params?.limit,
    },
  })
  const data = ensureSuccessEnvelope(response.data, 'boards')
  return Array.isArray(data.boards) ? data.boards.map(normalizeSummary) : []
}

export async function getCanvasBoard(id: number | string): Promise<CanvasBoard> {
  const response = await apiClient.get<unknown>(`/canvas/boards/${id}`)
  const data = ensureSuccessEnvelope(response.data, 'board')
  return normalizeBoard(data.board)
}

export async function createCanvasBoard(data: {
  title?: string
  subject?: string
  snapshot?: CanvasSnapshot
}): Promise<CanvasBoard> {
  const response = await apiClient.post<unknown>('/canvas/boards', data)
  const payload = ensureSuccessEnvelope(response.data, 'board')
  return normalizeBoard(payload.board)
}

export async function updateCanvasBoard(
  id: number | string,
  data: {
    title?: string
    subject?: string
    snapshot?: CanvasSnapshot
    expectedRevision?: number
  }
): Promise<UpdateCanvasBoardResult> {
  const response = await apiClient.put<unknown>(`/canvas/boards/${id}`, {
    title: data.title,
    subject: data.subject,
    snapshot: data.snapshot,
    expected_revision: data.expectedRevision,
  })
  const payload = response.data
  if (isRecord(payload) && payload.success === false && payload.conflict === true) {
    return {
      success: false,
      conflict: true,
      serverBoard: normalizeBoard(payload.server_board),
      error: toStringValue(payload.error),
    }
  }
  const ok = ensureSuccessEnvelope(payload, 'board')
  return { success: true, board: normalizeBoard(ok.board) }
}

export async function getCanvasBoardVersions(boardId: number | string, limit = 30): Promise<CanvasBoardVersion[]> {
  const response = await apiClient.get<unknown>(`/canvas/boards/${boardId}/versions`, { params: { limit } })
  const payload = ensureSuccessEnvelope(response.data, 'versions')
  return Array.isArray(payload.versions) ? payload.versions.map(normalizeVersion) : []
}

export async function createCanvasBoardVersion(boardId: number | string): Promise<{
  version: CanvasBoardVersion
  versions: CanvasBoardVersion[]
}> {
  const response = await apiClient.post<unknown>(`/canvas/boards/${boardId}/versions`)
  const payload = ensureSuccessEnvelope(response.data, 'version')
  return {
    version: normalizeVersion(payload.version),
    versions: Array.isArray(payload.versions) ? payload.versions.map(normalizeVersion) : [],
  }
}

export async function getCanvasBoardVersion(boardId: number | string, versionId: number | string): Promise<CanvasBoardVersion> {
  const response = await apiClient.get<unknown>(`/canvas/boards/${boardId}/versions/${versionId}`)
  const payload = ensureSuccessEnvelope(response.data, 'version')
  return normalizeVersion(payload.version)
}

export async function pickCanvasQuestions(
  boardId: number | string,
  payload: {
    requirement: string
    subject?: string
    eduLevel?: string
    count?: number
    limit?: number
    maxPages?: number
  }
): Promise<{ selectedIds: string[]; questions: PickedCanvasQuestion[] }> {
  const response = await apiClient.post<unknown>(`/canvas/boards/${boardId}/pick-questions`, {
    requirement: payload.requirement,
    subject: payload.subject,
    edu_level: payload.eduLevel,
    count: payload.count,
    limit: payload.limit,
    max_pages: payload.maxPages,
  })
  const data = ensureSuccessEnvelope(response.data, 'questions')
  return {
    selectedIds: Array.isArray(data.selected_ids) ? data.selected_ids.map(String) : [],
    questions: Array.isArray(data.questions)
      ? data.questions.filter(isRecord).map((question) => ({
          success: question.success !== false,
          questionId: toStringValue(question.question_id || question.questionId),
          title: toStringValue(question.title) || '题目',
          meta: isRecord(question.meta) ? question.meta : undefined,
          stemHtml: toStringValue(question.stem_html || question.stemHtml),
          type: toStringValue(question.type),
          difficulty: toStringValue(question.difficulty),
          knowledgePoints: Array.isArray(question.knowledge_points)
            ? question.knowledge_points.map(String)
            : Array.isArray(question.knowledgePoints)
              ? question.knowledgePoints.map(String)
              : undefined,
          source: toStringValue(question.source),
          url: toStringValue(question.url),
          selectReason: toStringValue(question.select_reason || question.selectReason),
        }))
      : [],
  }
}

export async function renderCanvasQuestion(
  questionId: string,
  params?: { subject?: string; eduLevel?: string }
): Promise<PickedCanvasQuestion> {
  const response = await apiClient.get<unknown>(`/canvas/questions/${encodeURIComponent(questionId)}/render`, {
    params: {
      subject: params?.subject,
      edu_level: params?.eduLevel,
    },
  })
  const data = ensureSuccessEnvelope(response.data, 'question')
  const question = isRecord(data.question) ? data.question : {}
  return {
    success: true,
    questionId: toStringValue(question.question_id || question.questionId || questionId),
    title: toStringValue(question.title) || '题目',
    meta: isRecord(question.meta) ? question.meta : undefined,
    stemHtml: toStringValue(question.stem_html || question.stemHtml),
    type: toStringValue(question.type),
    difficulty: toStringValue(question.difficulty),
    knowledgePoints: Array.isArray(question.knowledge_points)
      ? question.knowledge_points.map(String)
      : Array.isArray(question.knowledgePoints)
        ? question.knowledgePoints.map(String)
        : undefined,
    source: toStringValue(question.source),
    url: toStringValue(question.url),
    selectReason: toStringValue(question.select_reason || question.selectReason),
  }
}
