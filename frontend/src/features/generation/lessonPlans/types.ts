import type { TaskStep } from '@/types'

export interface SubAgentActivity {
  knowledgePoint: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  steps: TaskStep[]
}

