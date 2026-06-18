export type ComposeReviewStatus = 'approved' | 'rejected'

export type ComposeDraftQuestion = {
  questionId: string
  stem: string
  type: string
  difficulty: string
}

export type ComposeDraft = {
  paperName: string
  questions: ComposeDraftQuestion[]
}

export type ComposeReviewResult = {
  paperId: string
  name: string
  questionCount: number
}

export type StatusTone = 'default' | 'secondary' | 'destructive'

export type FormattedStatus = {
  label: string
  tone: StatusTone
}
