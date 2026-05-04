import { LONG_TASK_CREATE_TIMEOUT_MS, apiClient } from '../client'
import { streamTask, type TaskStreamEvent } from '@/api/tasks'
import type { Paper, PaperAnalysis, PaperSummary, Question } from '@/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function recordString(value: unknown, key: string): string | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return typeof item === 'string' ? item : undefined
}

function recordNumber(value: unknown, key: string): number | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return typeof item === 'number' ? item : undefined
}

function recordStringArray(value: unknown, key: string): string[] | undefined {
  if (!isRecord(value)) return undefined
  const item = value[key]
  return Array.isArray(item) ? item.filter((entry): entry is string => typeof entry === 'string') : undefined
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return recordString(error, 'message') || 'request_failed'
}

export interface GetPapersParams {
  limit?: number
}

export interface GetPaperOptions {
  includeAnalysis?: boolean
}

export interface CreatePaperRequest {
  name: string
  questionIds: string[]
}

export interface CreatePaperResponse {
  success: boolean
  paperId?: number
  message?: string
}

export interface PaperDownloadLink {
  success: boolean
  paperName?: string
  questionCount?: number
  questionIds?: string[]
  questionLinks?: string[]
  instructions?: string[]
}

export interface PaperExportRequest {
  format: 'markdown' | 'latex' | 'pdf' | 'docx'
  includeStem?: boolean
  includeAnswer?: boolean
  includeAnalysis?: boolean
}

export interface PaperExportResponse {
  success: boolean
  format?: string
  url?: string
  filename?: string
  // PDF export may return both PDF and TeX URLs
  pdfUrl?: string
  pdfFilename?: string
  texUrl?: string
  texFilename?: string
  error?: string
  log?: string
}

export interface GenerateFullPaperRequest {
  taskId?: string
  subject: string
  topic?: string
  paperName?: string
  totalPoints?: number
  total_points?: number
  timeLimit?: number
  time_limit?: number
  difficultyDistribution?: Record<string, unknown>
  difficulty_distribution?: Record<string, unknown>
  useStudyArchive?: boolean
  use_study_archive?: boolean
  streamReasoning?: boolean
  stream_reasoning?: boolean
}

export interface GenerateFullPaperStreamEvent {
  type: 'step' | 'progress' | 'result' | 'error' | string
  taskId?: string
  progress?: number
  step?: Record<string, unknown>
  result?: Record<string, unknown>
  error?: string
  data?: Record<string, unknown>
  message?: string
  [key: string]: unknown
}

export function generateFullPaperStream(
  request: GenerateFullPaperRequest,
  onEvent: (event: GenerateFullPaperStreamEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: () => void,
  options?: { signal?: AbortSignal }
): void {
  const payload = {
    ...request,
    totalPoints: request.totalPoints ?? request.total_points,
    timeLimit: request.timeLimit ?? request.time_limit,
    difficultyDistribution: request.difficultyDistribution ?? request.difficulty_distribution,
    streamReasoning: request.streamReasoning ?? request.stream_reasoning,
    useStudyArchive: request.useStudyArchive ?? request.use_study_archive,
  }

  apiClient
    .post('/tasks/papers/generate-full', payload, { signal: options?.signal, timeout: LONG_TASK_CREATE_TIMEOUT_MS })
    .then((res) => {
      const taskId = String(recordString(res.data, 'taskId') || request.taskId || '').trim()
      if (!taskId) throw new Error('missing_task_id')

      streamTask(
        taskId,
        0,
        (evt: TaskStreamEvent) => {
          if (evt.type === 'ping') return
          const data = isRecord(evt.data) ? evt.data : {}
          const out: GenerateFullPaperStreamEvent = { taskId: evt.taskId, type: String(evt.type || '') }

          if (evt.type === 'progress') {
            out.progress = typeof data.progress === 'number' ? data.progress : Number(data.progress)
          } else if (evt.type === 'step') {
            out.step = isRecord(data.step) ? data.step : undefined
          } else if (evt.type === 'result') {
            out.result = isRecord(data.result) ? data.result : undefined
          } else if (evt.type === 'error') {
            out.error = recordString(data, 'error') || recordString(data, 'message') || 'generate_full_failed'
            out.message = out.error
          } else {
            out.data = data
          }

          onEvent(out)
        },
        onError,
        onComplete,
        { signal: options?.signal }
      )
    })
    .catch((err: unknown) => {
      const message = errorMessage(err)
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

function toPaperAnalysis(input: unknown): PaperAnalysis | undefined {
  if (!isRecord(input)) return undefined
  const difficultyScore = Number(input.difficulty_score)
  const radarData = Array.isArray(input.radar_data)
    ? input.radar_data.filter((entry): entry is Record<string, unknown> => isRecord(entry))
    : []
  const aiComment =
    typeof input.ai_comment === 'string' ? input.ai_comment : ''

  if (!Number.isFinite(difficultyScore) && radarData.length === 0 && !aiComment)
    return undefined
  return {
    difficultyScore: Number.isFinite(difficultyScore) ? difficultyScore : 0,
    radarData,
    aiComment,
  }
}

function toQuestionMeta(input: unknown): Question | undefined {
  if (!isRecord(input)) return undefined
  const questionId =
    typeof input.question_id === 'string'
      ? input.question_id
      : ''
  if (!questionId) return undefined

  const order =
    typeof input.order === 'number' ? input.order : undefined
  const stem =
    typeof input.stem === 'string' ? input.stem : undefined

  return {
    questionId,
    order,
    type: typeof input.type === 'string' ? input.type : undefined,
    difficulty:
      typeof input.difficulty === 'string'
        ? input.difficulty
        : undefined,
    knowledgePoint:
      typeof input.knowledge_point === 'string'
        ? input.knowledge_point
        : undefined,
    sourceUrl:
      typeof input.source_url === 'string'
        ? input.source_url
        : undefined,
    stem,
  }
}

export async function getPapers(
  params: GetPapersParams = {}
): Promise<PaperSummary[]> {
  const response = await apiClient.get<unknown>('/papers', { params })
  const data = response.data
  const list = Array.isArray(data) ? data : []

  return list
    .filter((p): p is Record<string, unknown> => isRecord(p))
    .map((p) => ({
      id: Number(p.paper_id),
      name: recordString(p, 'paper_name') || String(p.paper_id),
      createdAt: recordString(p, 'created_at') || '',
      questionCount: Number(p.question_count ?? 0),
    }))
    .filter((p) => Number.isFinite(p.id) && !!p.name)
}

export async function getPaper(id: string, options: GetPaperOptions = {}): Promise<Paper> {
  const response = await apiClient.get<unknown>(`/papers/${id}`, {
    params: {
      include_analysis: options.includeAnalysis ? 1 : 0,
    },
  })
  const data = isRecord(response.data) ? response.data : {}

  const rawQuestions: unknown[] = Array.isArray(data.questions)
    ? data.questions
    : []
  const questions = rawQuestions
    .map(toQuestionMeta)
    .filter((q): q is Question => !!q)

  return {
    id: Number(data.paper_id),
    name: recordString(data, 'paper_name') || String(id),
    subject: recordString(data, 'subject'),
    createdAt: recordString(data, 'created_at') || '',
    questions,
    analysis: toPaperAnalysis(data.analysis),
  }
}

export async function createPaper(
  data: CreatePaperRequest
): Promise<CreatePaperResponse> {
  const response = await apiClient.post<unknown>('/papers', {
    paper_name: data.name,
    question_ids: data.questionIds,
  })
  const payload = isRecord(response.data) ? response.data : {}
  return {
    success: Boolean(payload.success),
    paperId: recordNumber(payload, 'paper_id'),
    message: recordString(payload, 'message'),
  }
}

export async function deletePaper(id: string): Promise<void> {
  await apiClient.delete(`/papers/${id}`)
}

export async function getPaperDownloadLink(id: string): Promise<PaperDownloadLink> {
  const response = await apiClient.get<unknown>(`/papers/${id}/download-link`)
  const data = isRecord(response.data) ? response.data : {}
  return {
    success: Boolean(data.success),
    paperName: recordString(data, 'paper_name'),
    questionCount:
      recordNumber(data, 'question_count'),
    questionIds: recordStringArray(data, 'question_ids'),
    questionLinks: recordStringArray(data, 'question_links'),
    instructions: recordStringArray(data, 'instructions'),
  }
}

export async function exportPaper(
  id: string,
  req: PaperExportRequest
): Promise<PaperExportResponse> {
  const response = await apiClient.post<unknown>(`/papers/${id}/export`, {
    format: req.format,
    includeStem: Boolean(req.includeStem),
    includeAnswer: Boolean(req.includeAnswer),
    includeAnalysis: Boolean(req.includeAnalysis),
  })
  const data = isRecord(response.data) ? response.data : {}

  return {
    success: Boolean(data.success),
    format: recordString(data, 'format'),
    url: recordString(data, 'url'),
    filename: recordString(data, 'filename'),
    pdfUrl: recordString(data, 'pdf_url'),
    pdfFilename: recordString(data, 'pdf_filename'),
    texUrl: recordString(data, 'tex_url'),
    texFilename: recordString(data, 'tex_filename'),
    error: recordString(data, 'error'),
    log: recordString(data, 'log'),
  }
}

export const papersApi = {
  getPapers,
  getPaper,
  createPaper,
  deletePaper,
  getPaperDownloadLink,
  exportPaper,
  generateFullPaperStream,
  list: async (): Promise<{ data: { papers: PaperSummary[] } }> => ({
    data: { papers: await getPapers({ limit: 100 }) },
  }),
  get: async (id: string): Promise<{ data: Paper }> => ({
    data: await getPaper(id, { includeAnalysis: true }),
  }),
  delete: async (id: string): Promise<{ data: { success: true } }> => {
    await deletePaper(id)
    return { data: { success: true } }
  },
}
