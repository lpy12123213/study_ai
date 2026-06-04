import { apiClient, resolveApiResourceUrl } from '@/api/client'
import type {
  ExamQuestion,
  ExamResult,
  ExamSession,
  ExamSessionStatus,
  SaveExamAnswerRequest,
  StartExamRequest,
  StudentAnswer,
} from '@/types/exam'

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object')
}

function readString(data: Record<string, unknown>, key: string): string {
  const value = data[key]
  return typeof value === 'string' ? value : ''
}

function readNumber(data: Record<string, unknown>, key: string): number {
  const value = data[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function readStringArray(data: Record<string, unknown>, key: string): string[] {
  const value = data[key]
  return Array.isArray(value) ? value.filter((x): x is string => typeof x === 'string') : []
}

function toStudentAnswer(input: unknown): StudentAnswer | undefined {
  if (!isRecord(input)) return undefined
  const questionId = readString(input, 'question_id') || readString(input, 'questionId')
  if (!questionId) return undefined
  const path = readString(input, 'handwriting_image_path') || readString(input, 'handwritingImagePath')
  return {
    questionId,
    questionType: readString(input, 'question_type') || readString(input, 'questionType'),
    questionOrder: readNumber(input, 'question_order') || undefined,
    selectedOptions: readStringArray(input, 'selected_options').length
      ? readStringArray(input, 'selected_options')
      : readStringArray(input, 'selectedOptions'),
    fillBlankText: readString(input, 'fill_blank_text') || readString(input, 'fillBlankText'),
    handwritingImagePath: path || undefined,
    handwritingImageUrl: path ? resolveApiResourceUrl(`/api/media/exam-handwriting/${path.split('/').slice(-2).join('/')}`) : undefined,
    textAnswer: readString(input, 'text_answer') || readString(input, 'textAnswer'),
    isCorrect: typeof input.is_correct === 'boolean' ? input.is_correct : typeof input.isCorrect === 'boolean' ? input.isCorrect : null,
    score: readNumber(input, 'score'),
    maxScore: readNumber(input, 'max_score') || readNumber(input, 'maxScore'),
    gradingJson: isRecord(input.grading_json) ? input.grading_json : isRecord(input.gradingJson) ? input.gradingJson : {},
    autoSavedAt: readString(input, 'auto_saved_at') || readString(input, 'autoSavedAt') || undefined,
  }
}

function toQuestion(input: unknown): ExamQuestion | undefined {
  if (!isRecord(input)) return undefined
  const questionId = readString(input, 'question_id') || readString(input, 'questionId')
  if (!questionId) return undefined
  const studentAnswer = toStudentAnswer(input.student_answer)
  return {
    questionId,
    order: readNumber(input, 'order'),
    type: readString(input, 'type'),
    questionType: readString(input, 'question_type') || readString(input, 'questionType') || readString(input, 'type'),
    stem: readString(input, 'stem'),
    difficulty: readString(input, 'difficulty') || undefined,
    knowledgePoint: readString(input, 'knowledge_point') || readString(input, 'knowledgePoint') || undefined,
    sourceUrl: readString(input, 'source_url') || readString(input, 'sourceUrl') || undefined,
    maxScore: readNumber(input, 'max_score') || readNumber(input, 'maxScore'),
    studentAnswer,
  }
}

function toSession(input: unknown): ExamSession {
  const data = isRecord(input) ? input : {}
  const rawQuestions = Array.isArray(data.questions) ? data.questions : []
  const rawAnswers = Array.isArray(data.answers) ? data.answers : []
  return {
    sessionId: readString(data, 'session_id') || readString(data, 'sessionId'),
    paperId: readNumber(data, 'paper_id') || readNumber(data, 'paperId'),
    paperName: readString(data, 'paper_name') || readString(data, 'paperName'),
    mode: readString(data, 'mode') === 'timed' ? 'timed' : 'untimed',
    timeLimitMinutes: readNumber(data, 'time_limit_minutes') || readNumber(data, 'timeLimitMinutes') || null,
    startedAt: readString(data, 'started_at') || readString(data, 'startedAt') || null,
    submittedAt: readString(data, 'submitted_at') || readString(data, 'submittedAt') || null,
    expiresAt: readString(data, 'expires_at') || readString(data, 'expiresAt') || null,
    status: (readString(data, 'status') || 'in_progress') as ExamSessionStatus,
    totalScore: readNumber(data, 'total_score') || readNumber(data, 'totalScore'),
    maxScore: readNumber(data, 'max_score') || readNumber(data, 'maxScore'),
    questions: rawQuestions.map(toQuestion).filter((q): q is ExamQuestion => Boolean(q)),
    answers: rawAnswers.map(toStudentAnswer).filter((a): a is StudentAnswer => Boolean(a)),
  }
}

function toResult(input: unknown): ExamResult {
  const data = isRecord(input) ? input : {}
  return {
    sessionId: readString(data, 'session_id') || readString(data, 'sessionId'),
    totalScore: readNumber(data, 'total_score') || readNumber(data, 'totalScore'),
    maxScore: readNumber(data, 'max_score') || readNumber(data, 'maxScore'),
    scoreRatio: readNumber(data, 'score_ratio') || readNumber(data, 'scoreRatio'),
    objectiveCorrect: readNumber(data, 'objective_correct') || readNumber(data, 'objectiveCorrect'),
    objectiveTotal: readNumber(data, 'objective_total') || readNumber(data, 'objectiveTotal'),
    subjectiveScore: readNumber(data, 'subjective_score') || readNumber(data, 'subjectiveScore'),
    subjectiveMax: readNumber(data, 'subjective_max') || readNumber(data, 'subjectiveMax'),
    breakdown: Array.isArray(data.breakdown) ? data.breakdown.filter(isRecord) : [],
    aiFeedback: isRecord(data.ai_feedback) ? data.ai_feedback : isRecord(data.aiFeedback) ? data.aiFeedback : {},
    createdAt: readString(data, 'created_at') || readString(data, 'createdAt') || null,
  }
}

export async function startExam(request: StartExamRequest): Promise<ExamSession> {
  const response = await apiClient.post('/exam/sessions', {
    paper_id: request.paperId,
    mode: request.mode,
    time_limit_minutes: request.timeLimitMinutes ?? null,
  })
  return toSession(response.data)
}

export async function getExamSession(sessionId: string, options: { includeAnswers?: boolean } = {}): Promise<ExamSession> {
  const response = await apiClient.get(`/exam/sessions/${sessionId}`, {
    params: { include_answers: options.includeAnswers ? 1 : 0 },
  })
  return toSession(response.data)
}

export async function getExamSessions(params: { paperId?: number; limit?: number } = {}): Promise<ExamSession[]> {
  const response = await apiClient.get('/exam/sessions', {
    params: {
      paper_id: params.paperId,
      limit: params.limit ?? 50,
    },
  })
  const list = Array.isArray(response.data) ? response.data : []
  return list.map(toSession)
}

export async function saveAnswer(sessionId: string, answer: SaveExamAnswerRequest): Promise<StudentAnswer> {
  const response = await apiClient.put(`/exam/sessions/${sessionId}/answers/${answer.questionId}`, {
    question_id: answer.questionId,
    question_type: answer.questionType,
    selected_options: answer.selectedOptions ?? [],
    fill_blank_text: answer.fillBlankText ?? '',
    handwriting_image_path: answer.handwritingImagePath ?? '',
    text_answer: answer.textAnswer ?? '',
  })
  const data = isRecord(response.data) ? response.data : {}
  return toStudentAnswer(data.answer) ?? {
    questionId: answer.questionId,
    selectedOptions: answer.selectedOptions ?? [],
    fillBlankText: answer.fillBlankText ?? '',
    textAnswer: answer.textAnswer ?? '',
  }
}

export async function batchSaveAnswers(sessionId: string, answers: SaveExamAnswerRequest[]): Promise<StudentAnswer[]> {
  const response = await apiClient.put(`/exam/sessions/${sessionId}/answers/batch`, {
    answers: answers.map((answer) => ({
      question_id: answer.questionId,
      question_type: answer.questionType,
      selected_options: answer.selectedOptions ?? [],
      fill_blank_text: answer.fillBlankText ?? '',
      handwriting_image_path: answer.handwritingImagePath ?? '',
      text_answer: answer.textAnswer ?? '',
    })),
  })
  const data = isRecord(response.data) ? response.data : {}
  const list = Array.isArray(data.answers) ? data.answers : []
  return list.map(toStudentAnswer).filter((a): a is StudentAnswer => Boolean(a))
}

export async function uploadHandwriting(sessionId: string, questionId: string, file: File): Promise<{ url: string; path: string }> {
  const form = new FormData()
  form.append('file', file)
  const response = await apiClient.post(`/exam/sessions/${sessionId}/answers/${questionId}/handwriting`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  const data = isRecord(response.data) ? response.data : {}
  const path = readString(data, 'path')
  return {
    url: resolveApiResourceUrl(readString(data, 'url')),
    path,
  }
}

export async function submitExam(sessionId: string): Promise<ExamResult> {
  const response = await apiClient.post(`/exam/sessions/${sessionId}/submit`)
  return toResult(response.data)
}

export async function getExamResult(sessionId: string): Promise<ExamResult> {
  const response = await apiClient.get(`/exam/sessions/${sessionId}/result`)
  return toResult(response.data)
}
