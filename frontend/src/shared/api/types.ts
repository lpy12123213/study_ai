/**
 * 后端契约类型与固定词表。
 * 来源：backend/api/** 的 Pydantic 模型与路由（2026-07 勘察）。
 */

// ---------------- 认证 ----------------
export interface UserInfo {
  user_id: string;
  username: string;
  role: string;
  created_at?: string | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: number;
  user: UserInfo;
}

// ---------------- 固定词表 ----------------
export const SUBJECTS = [
  "初中语文",
  "初中数学",
  "初中英语",
  "初中物理",
  "初中化学",
  "初中生物",
  "高中语文",
  "高中数学",
  "高中英语",
  "高中物理",
  "高中化学",
  "高中生物",
] as const;
export type Subject = (typeof SUBJECTS)[number];
export const DEFAULT_SUBJECT: Subject = "高中数学";

export const EDU_LEVELS = ["小学", "初中", "高中", "中职"] as const;

export const DIFFICULTIES = ["简单", "中等", "困难"] as const;
export type Difficulty = (typeof DIFFICULTIES)[number];

export const QUESTION_TYPES = [
  "单选题",
  "多选题",
  "选择题",
  "填空题",
  "解答题",
  "简答题",
  "计算题",
  "论述题",
] as const;

export const STUDY_PRESETS = [
  { value: "quick", label: "快速", desc: "轻量概要，分钟级完成" },
  { value: "standard", label: "标准", desc: "完整讲义结构，适合日常学习" },
  { value: "deep", label: "深入", desc: "大主题深挖，含证明与例题" },
  { value: "research", label: "研究", desc: "最长流程，调研级综述" },
] as const;
export type StudyPreset = (typeof STUDY_PRESETS)[number]["value"];

export const CONTINUE_MODES = [
  { value: "improve", label: "润色改进", desc: "在现有基础上提升表达与结构" },
  { value: "deepen_research", label: "加深研究", desc: "补充更多参考资料与证明" },
  { value: "fix_export", label: "重试导出", desc: "重新执行导出阶段" },
  { value: "skip_export", label: "跳过导出", desc: "仅保留 Markdown 结果" },
  { value: "resume_failed_stage", label: "恢复失败阶段", desc: "从失败的阶段继续" },
  { value: "retry_search", label: "重试检索", desc: "重新执行资料检索" },
  { value: "replan_from_failure", label: "重新规划", desc: "基于失败点重新制定计划" },
] as const;

// ---------------- 任务 ----------------
export type TaskStatus =
  | "running"
  | "paused"
  | "pending_review"
  | "completed"
  | "failed"
  | "canceled"
  | "cancelled";

export const TASK_STATUS_LABELS: Record<string, string> = {
  running: "运行中",
  paused: "已暂停",
  pending_review: "待审核",
  completed: "已完成",
  failed: "已失败",
  canceled: "已取消",
  cancelled: "已取消",
};

export const TASK_TYPE_LABELS: Record<string, string> = {
  deepthink: "深度解题",
  lesson_plan: "教案生成",
  paper_compose: "蓝图组卷",
  paper_generate_full: "整卷生成",
  study_materials: "学习资料",
  knowledge_video: "知识视频",
  question_evaluate: "好题鉴别",
  essay_evaluation: "作文批改",
  export_paper: "试卷导出",
  export_study_archive: "资料导出",
  question_library_crawl: "题库抓取",
  question_library_generate: "AI 出题",
  question_library_score: "题库评分",
  question_library_media_import: "媒体录入",
};

export interface TaskSummary {
  id: string;
  user_id?: string;
  task_type: string;
  title?: string;
  status: TaskStatus;
  progress: number;
  last_seq?: number;
  parent_task_id?: string | null;
  created_at?: string;
  updated_at?: string;
  started_at?: string | null;
  ended_at?: string | null;
  elapsed_s?: number;
  eta_s?: number;
}

export interface TaskStep {
  id: string;
  title: string;
  status: "running" | "completed" | "failed" | "paused" | "pending_review" | string;
  startTime?: string;
  endTime?: string;
  toolName?: string;
  input?: any;
  output?: any;
  error?: string;
}

/** SSE 统一信封（归一化后） */
export interface TaskEvent {
  type: string;
  data: any;
  seq: number;
  taskId?: string;
  raw?: any;
}

// ---------------- 题目 ----------------
export interface SearchQuestion {
  question_id: string;
  stem?: string;
  type?: string;
  difficulty?: string;
  knowledge_points?: string[] | string;
  source?: string;
  source_url?: string;
  date?: string;
  quality_score?: number | null;
  quality_flags?: string[];
  difficulty_value?: number | null;
}

export interface QuestionEvaluateResult {
  question_id?: string;
  verdict: "好题" | "普通题" | "差题" | string;
  overall_score: number;
  dimensions: { name: string; score: number; comment?: string }[];
  highlights?: string[];
  issues?: string[];
  summary?: string;
}

// ---------------- 试卷 ----------------
export interface PaperSummary {
  paper_id: number;
  user_id?: string;
  paper_name: string;
  created_at: string;
  question_count: number;
}

export interface PaperQuestion {
  question_id: string;
  order?: number;
  type?: string;
  difficulty?: string;
  knowledge_point?: string;
  source_url?: string;
  stem?: string;
}

export interface PaperAnalysis {
  difficulty_score?: number;
  radar_data?: Record<string, unknown>[];
  ai_comment?: string;
}

export interface PaperDetail {
  paper_id: number;
  paper_name: string;
  created_at: string;
  updated_at?: string;
  source_mode?: "zujuan" | "local" | "hybrid" | string;
  questions: PaperQuestion[];
  analysis?: PaperAnalysis;
}

export interface ExportResult {
  success: boolean;
  format?: string;
  url?: string;
  filename?: string;
  sha256?: string;
  bytes?: number;
  expires_at?: string;
  pdf_url?: string;
  pdf_filename?: string;
  tex_url?: string;
  tex_filename?: string;
  error?: string;
  log?: string;
  [k: string]: any;
}

// ---------------- 组卷蓝图 ----------------
export interface BlueprintSlot {
  questionType: string;
  count: number;
  difficulty?: string;
}

export interface Blueprint {
  id: string;
  name: string;
  subject: string;
  topic?: string;
  slots: BlueprintSlot[];
  createdAt?: string;
  updatedAt?: string;
}

// ---------------- 题库 ----------------
export interface LibraryItem {
  question_id: string;
  stem?: string;
  answer?: string;
  analysis?: string;
  question_type?: string;
  difficulty?: string;
  difficulty_value?: number | null;
  knowledge_point?: string;
  knowledge_points_json?: string;
  source?: string;
  source_url?: string;
  date?: string;
  quality_score?: number | null;
  subject?: string;
  origin?: "crawled" | "ai" | "media" | string;
  hidden?: boolean;
  starred?: boolean;
  ai_score?: number | null;
  ai_verdict?: string;
  ai_summary?: string;
  has_answer?: boolean;
  has_analysis?: boolean;
  updated_at?: string;
  created_at?: string;
  [k: string]: any;
}

export interface LibraryListResponse {
  total: number | null;
  include_total?: boolean;
  items: LibraryItem[];
  limit: number;
  offset: number;
}

export interface DraftQuestion {
  question_id: string;
  stem?: string;
  answer?: string;
  analysis?: string;
  keep?: boolean;
  review_status?: string;
  review?: {
    verdict?: string;
    overall_score?: number;
    dimensions?: { name: string; score: number; comment?: string }[];
    highlights?: string[];
    issues?: string[];
    summary?: string;
    model?: string;
  } | null;
  diagrams?: { kind?: string; url?: string; filename?: string; alt?: string; caption?: string; markdown?: string }[];
  [k: string]: any;
}

export interface LibraryPreview {
  success: boolean;
  preview_id: string;
  session_id?: string;
  task_id?: string;
  subject?: string;
  topic?: string;
  mode?: string;
  difficulty?: string;
  question_type?: string;
  count?: number;
  requested_count?: number;
  draft_count?: number;
  draft_questions: DraftQuestion[];
  intuition_practice?: any;
}

export interface LibrarySession {
  session_id: string;
  preview_id?: string;
  status: string;
  mode?: string;
  subject?: string;
  topic?: string;
  count?: number;
  requested_count?: number;
  draft_count?: number;
  task_ids?: string[];
  latest_task_id?: string;
  updated_at_s?: number;
  created_at_s?: number;
  [k: string]: any;
}

// ---------------- 学习资料 ----------------
export interface StudyArchiveSummary {
  id: number;
  user_id?: string;
  subject?: string;
  topic?: string;
  preset?: string;
  created_at?: string;
  updated_at?: string | null;
}

export interface StudyArchive extends StudyArchiveSummary {
  markdown?: string;
  sections?: Record<string, unknown>[];
  acceptance?: Record<string, unknown>;
  requirements?: string;
  fingerprint?: string;
}

export interface StudyMaterialResult {
  success?: boolean;
  material?: {
    topic?: string;
    subject?: string;
    markdown?: string;
    passed?: boolean;
    issues?: string[];
    error?: string;
    md_url?: string;
    md_filename?: string;
    tex_url?: string;
    tex_filename?: string;
    pdf_url?: string;
    pdf_filename?: string;
    expires_at?: string;
    [k: string]: any;
  };
  acceptance?: Record<string, unknown>;
  workflow?: Record<string, unknown>;
  [k: string]: any;
}

// ---------------- 对话 ----------------
export interface Conversation {
  id: number;
  user_id?: string;
  title: string;
  created_at?: string;
  updated_at?: string;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant" | "tool" | string;
  content: string;
  /** 后端返回已解析的 JSON 数组（DB 中为 JSON 字符串，仓储层 json.loads 后下发） */
  tool_calls?: Record<string, any>[] | string | null;
  tool_call_id?: string | null;
  created_at?: string;
  tool_result_meta?: { size?: number; success?: boolean; error?: string } | null;
}

// ---------------- 系统 ----------------
export interface AppConfig {
  model_config_path?: string;
  llm_provider_pinned?: boolean;
  llm_active_provider?: string;
  chat_provider?: string;
  main_model?: string;
  sub_model?: string;
  default_subject?: string;
  chat_configured?: boolean;
  lesson_plan_configured?: boolean;
  openrouter_configured?: boolean;
  moonshot_configured?: boolean;
  fireworks_configured?: boolean;
  zhipu_configured?: boolean;
  metaso_configured?: boolean;
  tavily_configured?: boolean;
  [k: string]: any;
}

export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy" | string;
  service?: string;
  checks?: {
    db?: { ok: boolean; error?: string };
    disk?: { ok: boolean; [k: string]: any };
    llm?: { ok?: boolean; configured?: boolean; providers?: Record<string, any>; status?: string };
  };
  [k: string]: any;
}

export interface ModelProviderInfo {
  name: string;
  base_url?: string;
  api_key_set?: boolean;
  api_key_mask?: string;
  api_key_encrypted?: boolean;
}

export interface ModelSettings {
  active_provider?: string;
  pinned?: boolean;
  providers?: ModelProviderInfo[];
  models?: Record<string, any>;
  params?: Record<string, any>;
  config_path?: string;
  runtime?: { reloaded?: boolean; active_provider?: string; main_model?: string; sub_model?: string };
  [k: string]: any;
}

export interface DashboardStats {
  from?: string;
  to?: string;
  tasks_total?: number;
  tasks_by_type?: Record<string, number>;
  tasks_by_status?: Record<string, number>;
  completion_rate?: number;
  avg_duration_s?: number;
  exports_total?: number;
  exports_by_type?: Record<string, number>;
  top_subjects?: { subject: string; count: number }[];
}

export interface GlobalSearchResult {
  type: string;
  title: string;
  snippet: string;
  score: number;
  conversation_id?: number;
  message_id?: number;
  paper_id?: number;
  question_id?: string;
  archive_id?: number;
  /** 实体聚合后的命中条数（如一个会话里匹配的消息数）；1:N 实体才有意义。 */
  match_count?: number;
}

export interface ExportFileInfo {
  filename: string;
  user_id?: string;
  file_type?: string;
  mime_type?: string;
  sha256?: string;
  bytes: number;
  created_at?: string;
  expires_at?: string;
}

// ---------------- 分享 ----------------
export interface ShareMeta {
  success?: boolean;
  token?: string;
  item_type?: "paper" | "study_archive" | "template" | string;
  expires_at?: string | null;
  created_at?: string;
  has_password?: boolean;
  [k: string]: any;
}

// ---------------- 组卷 compose ----------------
export interface ComposeSlot {
  questionType: string;
  count: number;
  difficulty?: string;
}

export interface ComposeFilters {
  gradeId?: number;
  textbookVersion?: string;
  provinceId?: number;
  paperTypeId?: number;
}

export interface ComposeOptions {
  maxPages?: number;
  perSlotExpand?: number;
  minQualityScore?: number;
  dedupByStem?: boolean;
  avoidUsed?: boolean;
  autoAiBackfill?: boolean;
  maxAiQuestionsPerPaper?: number;
  aiAnswerSynthesis?: boolean;
  autoReview?: boolean;
  requireHumanReview?: boolean;
  judgePassScore?: number;
  [k: string]: any;
}

export interface ComposeDraftQuestion {
  questionId?: string;
  question_id?: string;
  order?: number;
  type?: string;
  difficulty?: string;
  knowledgePoint?: string;
  knowledge_point?: string;
  sourceUrl?: string;
  source_url?: string;
  stem?: string;
  answer?: string;
  analysis?: string;
  [k: string]: any;
}

export interface ComposeDraft {
  paperName?: string;
  questions?: ComposeDraftQuestion[];
  [k: string]: any;
}
