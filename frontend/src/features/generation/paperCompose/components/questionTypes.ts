export interface QuestionTypeOption {
  id: string
  name: string
  defaultScore: number
}

export const defaultQuestionTypes: QuestionTypeOption[] = [
  { id: 'single_choice', name: '单选题', defaultScore: 3 },
  { id: 'multi_choice', name: '多选题', defaultScore: 4 },
  { id: 'fill_blank', name: '填空题', defaultScore: 4 },
  { id: 'short_answer', name: '简答题', defaultScore: 8 },
  { id: 'calculation', name: '计算题', defaultScore: 10 },
  { id: 'essay', name: '论述题', defaultScore: 12 },
]
