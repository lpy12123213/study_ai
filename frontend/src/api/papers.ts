import { apiClient } from './client'
import { streamTask, type TaskStreamEvent } from '@/api/tasks'
import type { Paper, PaperAnalysis, PaperSummary, Question } from '@/types'

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
  timeLimit?: number
  difficultyDistribution?: Record<string, unknown>
  useStudyArchive?: boolean
  streamReasoning?: boolean
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
  [key: string]: any
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
    totalPoints: request.totalPoints ?? (request as any).total_points,
    timeLimit: request.timeLimit ?? (request as any).time_limit,
    difficultyDistribution: request.difficultyDistribution ?? (request as any).difficulty_distribution,
    streamReasoning: request.streamReasoning ?? (request as any).stream_reasoning,
    useStudyArchive: request.useStudyArchive ?? (request as any).use_study_archive,
  }

  apiClient
    .post('/tasks/papers/generate-full', payload, { signal: options?.signal })
    .then((res) => {
      const taskId = String((res.data as any)?.taskId || request.taskId || '').trim()
      if (!taskId) throw new Error('missing_task_id')

      streamTask(
        taskId,
        0,
        (evt: TaskStreamEvent) => {
          if (evt.type === 'ping') return
          const data = evt.data && typeof evt.data === 'object' ? (evt.data as Record<string, unknown>) : {}
          const out: GenerateFullPaperStreamEvent = { taskId: evt.taskId, type: String(evt.type || '') }

          if (evt.type === 'progress') {
            out.progress = typeof (data as any).progress === 'number' ? (data as any).progress : Number((data as any).progress)
          } else if (evt.type === 'step') {
            out.step = (data as any).step
          } else if (evt.type === 'result') {
            out.result = (data as any).result
          } else if (evt.type === 'error') {
            out.error =
              typeof (data as any).error === 'string'
                ? (data as any).error
                : typeof (data as any).message === 'string'
                  ? (data as any).message
                  : 'generate_full_failed'
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
    .catch((err: any) => {
      const message = typeof err?.message === 'string' ? err.message : 'request_failed'
      onError?.(err instanceof Error ? err : new Error(message))
    })
}

function toPaperAnalysis(input: any): PaperAnalysis | undefined {
  if (!input || typeof input !== 'object') return undefined
  const difficultyScore = Number((input as any).difficulty_score)
  const radarData = Array.isArray((input as any).radar_data)
    ? ((input as any).radar_data as Record<string, unknown>[])
    : []
  const aiComment =
    typeof (input as any).ai_comment === 'string' ? (input as any).ai_comment : ''

  if (!Number.isFinite(difficultyScore) && radarData.length === 0 && !aiComment)
    return undefined
  return {
    difficultyScore: Number.isFinite(difficultyScore) ? difficultyScore : 0,
    radarData,
    aiComment,
  }
}

function toQuestionMeta(input: any): Question | undefined {
  if (!input || typeof input !== 'object') return undefined
  const questionId =
    typeof (input as any).question_id === 'string'
      ? (input as any).question_id
      : ''
  if (!questionId) return undefined

  const order =
    typeof (input as any).order === 'number' ? (input as any).order : undefined
  const stem =
    typeof (input as any).stem === 'string' ? (input as any).stem : undefined

  return {
    questionId,
    order,
    type: typeof (input as any).type === 'string' ? (input as any).type : undefined,
    difficulty:
      typeof (input as any).difficulty === 'string'
        ? (input as any).difficulty
        : undefined,
    knowledgePoint:
      typeof (input as any).knowledge_point === 'string'
        ? (input as any).knowledge_point
        : undefined,
    sourceUrl:
      typeof (input as any).source_url === 'string'
        ? (input as any).source_url
        : undefined,
    stem,
  }
}

export async function getPapers(
  params: GetPapersParams = {}
): Promise<PaperSummary[]> {
  const response = await apiClient.get<unknown>('/papers', { params })
  const data = response.data as any
  const list = Array.isArray(data) ? data : []

  return list
    .filter((p) => p && typeof p === 'object')
    .map((p) => ({
      id: Number(p.paper_id),
      name: typeof p.paper_name === 'string' ? p.paper_name : String(p.paper_id),
      createdAt: typeof p.created_at === 'string' ? p.created_at : '',
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
  const data = response.data as any

  const rawQuestions: unknown[] = Array.isArray(data?.questions)
    ? (data.questions as unknown[])
    : []
  const questions = rawQuestions
    .map(toQuestionMeta)
    .filter((q): q is Question => !!q)

  return {
    id: Number(data?.paper_id),
    name: typeof data?.paper_name === 'string' ? data.paper_name : String(id),
    subject: typeof data?.subject === 'string' ? data.subject : undefined,
    createdAt: typeof data?.created_at === 'string' ? data.created_at : '',
    questions,
    analysis: toPaperAnalysis(data?.analysis),
  }
}

export async function createPaper(
  data: CreatePaperRequest
): Promise<CreatePaperResponse> {
  const response = await apiClient.post<unknown>('/papers', {
    paper_name: data.name,
    question_ids: data.questionIds,
  })
  const payload = response.data as any
  return {
    success: Boolean(payload?.success),
    paperId: typeof payload?.paper_id === 'number' ? payload.paper_id : undefined,
    message: typeof payload?.message === 'string' ? payload.message : undefined,
  }
}

export async function deletePaper(id: string): Promise<void> {
  await apiClient.delete(`/papers/${id}`)
}

export async function getPaperDownloadLink(id: string): Promise<PaperDownloadLink> {
  const response = await apiClient.get<unknown>(`/papers/${id}/download-link`)
  const data = response.data as any
  return {
    success: Boolean(data?.success),
    paperName: typeof data?.paper_name === 'string' ? data.paper_name : undefined,
    questionCount:
      typeof data?.question_count === 'number' ? data.question_count : undefined,
    questionIds: Array.isArray(data?.question_ids) ? data.question_ids : undefined,
    questionLinks: Array.isArray(data?.question_links)
      ? data.question_links
      : undefined,
    instructions: Array.isArray(data?.instructions) ? data.instructions : undefined,
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
  const data = response.data as any

  return {
    success: Boolean(data?.success),
    format: typeof data?.format === 'string' ? data.format : undefined,
    url: typeof data?.url === 'string' ? data.url : undefined,
    filename: typeof data?.filename === 'string' ? data.filename : undefined,
    pdfUrl: typeof data?.pdf_url === 'string' ? data.pdf_url : undefined,
    pdfFilename: typeof data?.pdf_filename === 'string' ? data.pdf_filename : undefined,
    texUrl: typeof data?.tex_url === 'string' ? data.tex_url : undefined,
    texFilename: typeof data?.tex_filename === 'string' ? data.tex_filename : undefined,
    error: typeof data?.error === 'string' ? data.error : undefined,
    log: typeof data?.log === 'string' ? data.log : undefined,
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
  list: async (): Promise<{ data: any }> => ({
    data: { papers: await getPapers({ limit: 100 }) },
  }),
  get: async (id: string): Promise<{ data: any }> => ({
    data: await getPaper(id, { includeAnalysis: true }),
  }),
  delete: async (id: string): Promise<{ data: any }> => {
    await deletePaper(id)
    return { data: { success: true } }
  },
}
