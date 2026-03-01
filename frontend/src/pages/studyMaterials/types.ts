export type TriState = 'default' | 'on' | 'off'

export interface SubAgentActivity {
  knowledgePoint: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  steps: import('@/types').TaskStep[]
}

export type LatexLessonPlanOption = {
  id: string
  sourceType?: 'lesson_plan' | 'study_materials'
  title?: string
  subject?: string
  grade?: string
  createdAt?: string
  mdUrl: string
  mdFilename?: string
}

