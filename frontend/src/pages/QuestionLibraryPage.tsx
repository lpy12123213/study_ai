import { useSearchParams } from 'react-router-dom'
import { QuestionLibraryBrowser } from '@/features/generation/questionLibrary/QuestionLibraryBrowser'

export default function QuestionLibraryPage() {
  const [searchParams] = useSearchParams()
  const focusQuestionId = (searchParams.get('focus') || '').trim()

  return <QuestionLibraryBrowser focusQuestionId={focusQuestionId} />
}

