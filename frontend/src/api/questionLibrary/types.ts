import type { SseEnvelope } from '@/lib/sse'

export type QuestionOrigin = 'crawled' | 'ai' | 'media' | string

export interface QuestionLibraryListItem {
  question_id: string
  subject: string
  origin: QuestionOrigin
  hidden: boolean
  starred?: boolean
  has_answer?: boolean
  has_analysis?: boolean
  ai_score?: number | null
  ai_verdict?: string
  ai_dimensions_json?: string
  ai_summary?: string
  thinking_depth_score?: number | null
  thinking_method_family?: string
  thinking_method_signature?: string
  thinking_method_rarity?: string
  thinking_method_count?: number | null
  thinking_depth_comment?: string
  updated_at?: string
  stem?: string
  question_type?: string
  difficulty?: string
  difficulty_value?: number | null
  knowledge_point?: string
  knowledge_points_json?: string
  source_url?: string
  quality_score?: number | null
  source?: string
  date?: string
}

export interface QuestionLibraryListResponse {
  total: number | null
  include_total?: boolean
  limit: number
  offset: number
  items: QuestionLibraryListItem[]
}

export interface QuestionLibraryListParams {
  subject?: string
  origin?: QuestionOrigin
  hidden?: '0' | '1' | 'all'
  q?: string
  min_score?: number
  sort?: 'updated_at' | 'ai_score' | string
  order?: 'desc' | 'asc' | string
  limit?: number
  offset?: number
  include_total?: boolean
}

export interface QuestionCacheRecord {
  question_id: string
  subject?: string
  question_type?: string
  difficulty?: string
  knowledge_point?: string
  source_url?: string
  stem?: string
  answer?: string
  analysis?: string
  updated_at?: string
}

export interface QuestionLibraryDetailResponse {
  library_item: QuestionLibraryListItem | null
  question_cache: QuestionCacheRecord | null
}

export interface CrawlQuestionsPayload {
  subject: string
  edu_level?: string
  query: string
  difficulty?: string
  question_type?: string
  limit?: number
  max_pages?: number
  min_quality_score?: number
  difficulty_value_min?: number
  difficulty_value_max?: number
  require_difficulty_value?: boolean
  task_id?: string
}

export interface GenerateQuestionsPayload {
  subject: string
  topic: string
  difficulty?: string
  question_type?: string
  count?: number
  use_study_archive?: boolean
  use_reference_questions?: boolean
  reference_source?: 'any' | 'gaokao' | 'mock' | 'joint'
  reference_year_range?: 'all' | '3' | '5'
  session_id?: string
  mode?: 'standard' | 'infinite'
  grade_id?: string
  textbook_version_id?: string
  knowledge_point_ids?: string[]
  knowledge_points?: string[]
  append?: boolean
  stream_reasoning?: boolean
  task_id?: string
}

export interface ImportMediaQuestionsPayload {
  subject: string
  topic?: string
  difficulty?: string
  question_type?: string
  count?: number
  max_pdf_pages?: number
  task_id?: string
  files: File[]
}

export interface QuestionLibraryDraftQuestion {
  question_id: string
  stem: string
  answer: string
  analysis: string
  keep?: boolean
  diagrams?: Array<{
    kind?: string
    url: string
    filename?: string
    media_id?: string
    alt?: string
    caption?: string
    markdown?: string
  }>
  review_status?: 'pending_review' | 'in_review' | 'approved' | 'rejected' | 'confirmed' | 'committed'
  review?: {
    verdict: string
    overall_score: number
    dimensions: Array<{ name: string; score: number; comment: string }>
    highlights: string[]
    issues: string[]
    summary: string
    model: string
  } | null
}

export interface QuestionLibraryPreviewResponse {
  success: boolean
  preview_id: string
  session_id?: string
  task_id?: string
  subject: string
  topic: string
  mode?: 'standard' | 'infinite'
  difficulty?: string
  question_type?: string
  use_study_archive?: boolean
  use_reference_questions?: boolean
  reference_source?: 'any' | 'gaokao' | 'mock' | 'joint'
  reference_year_range?: 'all' | '3' | '5'
  count: number
  draft_questions: QuestionLibraryDraftQuestion[]
}

export interface QuestionLibraryLatestPendingPreviewResponse {
  success: boolean
  preview: Omit<QuestionLibraryPreviewResponse, 'success'> | null
}

export interface QuestionLibraryCommitPreviewResponse {
  success: boolean
  preview_id: string
  inserted: number
  subject: string
  count: number
  question_ids: string[]
}

export interface RegenerateQuestionLibrarySectionPayload {
  question_id: string
  section_key: 'stem' | 'answer' | 'analysis'
}

export interface RegenerateQuestionLibrarySectionEvent {
  preview_id?: string
  question_id?: string
  section_key?: 'stem' | 'answer' | 'analysis'
  content?: string
  stage?: string
  progress?: number
  draft_question?: QuestionLibraryDraftQuestion
  message?: string
}

export interface QuestionLibraryReasoningBlock {
  id: string
  task_id?: string
  stage_id?: string
  stage_label?: string
  source?: 'raw' | 'trace' | string
  content: string
  created_at?: string
}

export interface QuestionLibrarySessionSummary {
  session_id: string
  preview_id?: string
  status: string
  mode: 'standard' | 'infinite' | string
  subject: string
  topic: string
  count: number
  use_reference_questions?: boolean
  reference_source?: 'any' | 'gaokao' | 'mock' | 'joint'
  reference_year_range?: 'all' | '3' | '5'
  task_ids: string[]
  latest_task_id?: string
  updated_at_s?: number
  created_at_s?: number
  reasoning_blocks_count?: number
  confirmed_question_ids?: string[]
  stop_requested?: boolean
}

export interface QuestionLibrarySessionDetail extends QuestionLibrarySessionSummary {
  difficulty?: string
  question_type?: string
  use_study_archive?: boolean
  grade_id?: string
  textbook_version_id?: string
  knowledge_point_ids?: string[]
  knowledge_points?: string[]
  stream_reasoning?: boolean
  draft_questions: QuestionLibraryDraftQuestion[]
  reasoning_blocks: QuestionLibraryReasoningBlock[]
  task_events: SseEnvelope[]
}

export interface ScoreQuestionLibraryBatchPayload {
  subject: string
  limit?: number
  batch_size?: number
  only_unscored?: boolean
  task_id?: string
}

export interface ExportQuestionToBasketResponse {
  success?: boolean
  [key: string]: unknown
}

export interface ScoreQuestionLibraryBatchResponse {
  success?: boolean
  [key: string]: unknown
}

export type QuestionLibraryCompatListResponse = {
  questions: Array<{ id: string; content: string; type: string }>
}
