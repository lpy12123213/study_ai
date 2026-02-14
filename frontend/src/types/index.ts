// Task and Step types for Manus-style timeline
export type StepStatus = 'pending' | 'running' | 'completed' | 'failed' | 'paused';

export interface TaskStep {
  id: string;
  title: string;
  status: StepStatus;
  toolName?: string;
  input?: unknown;
  output?: unknown;
  startTime?: string;
  endTime?: string;
  error?: string;
  children?: TaskStep[];
}

export interface ResumableTask {
  taskId: string;
  taskType: 'blueprint' | 'lesson_plan' | 'study_materials' | 'chat';
  status: 'running' | 'paused' | 'completed' | 'failed';
  currentStep: number;
  totalSteps: number;
  checkpoint: {
    completedSteps: TaskStep[];
    pendingSteps: TaskStep[];
    context: unknown;
  };
  canResume: boolean;
}

// Conversation types
export type ConversationType = 'chat' | 'blueprint' | 'lesson_plan' | 'study_materials';
export type ConversationStatus = 'active' | 'completed' | 'paused';

export interface ConversationItem {
  id: string;
  title: string;
  type: ConversationType;
  createdAt: string;
  updatedAt: string;
  status: ConversationStatus;
  resumable: boolean;
  progress?: number;
  activeStream?: {
    taskType: 'study_materials';
    taskId: string;
    assistantMessageId: string;
    lastSeq: number;
  };
}

// Message types
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  createdAt: string;
  steps?: TaskStep[];
  attachment?:
    | {
        type: 'lesson_plan'
        lessonPlanId: string
      }
}

// Paper types (aligned with backend `/api/papers`)
export interface Question {
  questionId: string
  order?: number
  type?: string
  difficulty?: string
  knowledgePoint?: string
  sourceUrl?: string
}

export interface PaperAnalysis {
  difficultyScore: number
  radarData: Record<string, unknown>[]
  aiComment: string
}

export interface Paper {
  id: number
  name: string
  createdAt: string
  questions: Question[]
  analysis?: PaperAnalysis
}

export interface PaperSummary {
  id: number
  name: string
  createdAt: string
  questionCount: number
}

// Blueprint types
export interface BlueprintSlot {
  id: string;
  questionType: string;
  count: number;
  difficulty?: string;
  score?: number;
  tags?: string[];
}

export interface Blueprint {
  id: string;
  name: string;
  subject: string;
  slots: BlueprintSlot[];
  createdAt: string;
}

// Lesson Plan types
export interface LessonPlan {
  id: string;
  title: string;
  subject: string;
  grade: string;
  objectives: string[];
  duration: number;
  createdAt: string;

  // Generated document download links (new pipeline).
  mdUrl?: string;
  pdfUrl?: string;
  texUrl?: string;
  mdFilename?: string;
  pdfFilename?: string;
  texFilename?: string;

  // Legacy field: older versions stored the generated Markdown as `content`.
  content?: string;
}

// Subject types
export interface Subject {
  id: string;
  name: string;
  code: string;
  shortName?: string;
  bankId?: number;
  eduId?: number;
}

// User types
export interface User {
  id: string;
  username: string;
  email?: string;
  avatar?: string;
  role?: string;
}

// API Response types
export interface ApiResponse<T> {
  data: T;
  message?: string;
  success: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}
