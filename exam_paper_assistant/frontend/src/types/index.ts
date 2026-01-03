export interface Paper {
  paper_id: number;
  paper_name: string;
  created_at: string;
  question_count?: number;
  questions?: Question[];
  analysis?: AnalysisResult | null;
}

export interface Question {
  question_id: string;
  order?: number | null;
  type?: string | null;
  difficulty?: string | null;
  knowledge_point?: string | null;
  source_url?: string | null;
}

export interface AnalysisResult {
  difficulty_score: number;
  radar_data: Array<Record<string, unknown>>;
  ai_comment: string;
}

export interface PaperResponse {
  success: true;
  paper_id: number;
  message: string;
}

export interface DownloadLinkResponse {
  success: true;
  paper_name: string;
  question_count?: number;
  question_ids: string[];
  question_links: string[];
  instructions: string[];
}

export interface Conversation {
  id: number;
  title: string;
  created_at?: string;
  updated_at?: string;
}

export interface Message {
  id: number;
  role: "user" | "assistant" | "tool";
  content: string;
  created_at: string;
  tool_calls?: Array<Record<string, unknown>> | null;
  tool_call_id?: string | null;
}

export interface ConversationDetail {
  conversation: Conversation;
  messages: Message[];
}

export interface Subject {
  name: string;
  short_name: string;
  bank_id: number;
  edu_id: number;
}

export interface HealthResponse {
  status: string;
  service: string;
}

export type RuntimeConfig = Record<string, unknown>;

export type NameIdOption = {
  id: number | string;
  name: string;
};

export type AvailableFiltersRequest = {
  subject: string;
  edu_level?: string;
};

export type AvailableFiltersResponse = {
  success: boolean;
  subject?: string;
  bank_id?: number;
  default_category_id?: string;
  grades?: Array<{ id: number; name: string }>;
  paper_types_by_grade?: Record<string, Array<{ id: number; name: string; parent_id: number }>>;
  textbook_versions?: Array<{ id: string; name: string }>;
  question_types?: Array<{ id: number; name: string }>;
  provinces?: Array<{ id: number; name: string }>;
  elective_modes?: string[];
  applied_subject?: string;
  applied_edu_level?: string;
  error?: string;
};

export type BlueprintSlot = {
  keyword?: string;
  knowledge_point?: string;
  count: number;
  difficulty?: string;
  question_type?: string;
  source_contains?: string;
  stem_contains?: string;
  knowledge_contains?: string;
  max_pages?: number;
};

export type ComposeBlueprintRequest = {
  blueprint: BlueprintSlot[];
  subject: string;
  edu_level?: string;
  learn_grade?: string;
  learn_grade_id?: number;
  textbook_version?: string;
  elective_mode?: string;
  elective_keywords?: string[] | null;
  exclude_elective?: boolean;
  year?: number;
  province?: string;
  province_id?: number;
  paper_type_id?: number;
  term?: number;
  order_by?: number;
  max_pages?: number;
  per_slot_expand?: number;
  min_quality_score?: number;
  dedup_by_stem?: boolean;
  strict_subject?: boolean;
};

export type BlueprintRelaxTraceItem = {
  attempt: number;
  action: string;
  max_pages: number;
  min_quality_score: number;
  dedup_by_stem: boolean;
  fetched: boolean;
  fetch_success: boolean;
  fetch_error: string;
  candidate_pool: number;
  selected_total: number;
  requested: number;
};

export type BlueprintSectionResult = {
  index: number;
  slot: BlueprintSlot;
  success: boolean;
  error?: string;
  requested: number;
  selected: number;
  question_ids: string[];
  relax_trace?: BlueprintRelaxTraceItem[];
};

export type BlueprintQuestionPreview = {
  question_id: string;
  type?: string;
  difficulty?: string;
  difficulty_value?: number;
  source?: string;
  date?: string;
  source_url?: string;
  quality_score?: number;
  quality_flags?: string[];
};

export type ComposeBlueprintResponse = {
  success: boolean;
  count?: number;
  question_ids?: string[];
  sections?: BlueprintSectionResult[];
  questions_preview?: BlueprintQuestionPreview[];
  applied_subject?: string;
  applied_edu_level?: string;
  error?: string;
};

export type CanvasBoardSummary = {
  id: number;
  title: string;
  subject: string;
  revision: number;
  created_at: string;
  updated_at: string;
};

export type CanvasBoardDetail = CanvasBoardSummary & {
  snapshot: Record<string, unknown>;
};

export type CanvasBoardVersion = {
  id: number;
  board_id: number;
  revision: number;
  created_at: string;
};

export type CanvasBoardVersionDetail = CanvasBoardVersion & {
  snapshot: Record<string, unknown>;
};

export type CanvasPickedQuestion = {
  success: boolean;
  question_id: string;
  title: string;
  meta: string;
  stem_html: string;
  type?: string;
  difficulty?: string;
  knowledge_points?: string;
  source?: string;
  url?: string;
  select_reason?: string;
  error?: string;
};
