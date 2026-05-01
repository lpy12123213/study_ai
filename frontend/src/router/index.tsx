import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RequireAuth } from '@/layouts/RequireAuth'
import { ManusLayout } from '@/layouts/ManusLayout'

const load = (factory: () => Promise<{ default: React.ComponentType }>) => {
  const C = lazy(factory)
  return (
    <Suspense fallback={<div className="flex h-full items-center justify-center text-muted-foreground text-sm">加载中...</div>}>
      <C />
    </Suspense>
  )
}

export const router = createBrowserRouter([
  { path: '/login', element: <Navigate to="/dashboard" replace /> },
  { path: '/share/:token', element: load(() => import('@/pages/share/SharePage')) },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <ManusLayout />,
        children: [
          { index: true, element: <Navigate to="/dashboard" replace /> },
          { path: '/dashboard', element: load(() => import('@/pages/dashboard/DashboardPage')) },
          { path: '/chat', element: load(() => import('@/pages/chat/ChatPage')) },
          { path: '/chat/:conversationId', element: load(() => import('@/pages/chat/ChatPage')) },
          { path: '/blueprint', element: load(() => import('@/pages/blueprint/BlueprintPage')) },
          { path: '/lesson-plans', element: load(() => import('@/pages/lesson-plans/LessonPlansPage')) },
          { path: '/lesson-plans/:id', element: load(() => import('@/pages/lesson-plans/LessonPlanDetailPage')) },
          { path: '/study-materials', element: load(() => import('@/pages/study-materials/StudyMaterialsPage')) },
          { path: '/deepthink', element: load(() => import('@/pages/deepthink/DeepThinkPage')) },
          { path: '/question-evaluate', element: load(() => import('@/pages/question-evaluate/QuestionEvaluatePage')) },
          { path: '/question-library', element: load(() => import('@/pages/question-library/QuestionLibraryPage')) },
          { path: '/ai-generate', element: load(() => import('@/pages/ai-generate/AiGeneratePage')) },
          { path: '/ai-generate/review/:sessionId/:questionId', element: load(() => import('@/pages/ai-generate/QuestionReviewPage')) },
          { path: '/papers', element: load(() => import('@/pages/papers/PapersPage')) },
          { path: '/papers/:paperId', element: load(() => import('@/pages/papers/PaperDetailPage')) },
          { path: '/canvas', element: load(() => import('@/pages/canvas/CanvasPage')) },
          { path: '/settings', element: load(() => import('@/pages/settings/SettingsPage')) },
          { path: '/tasks', element: load(() => import('@/pages/tasks/TaskCenterPage')) },
          { path: '/search', element: load(() => import('@/pages/search/SearchPage')) },
          { path: '/study-archives/:archiveId', element: load(() => import('@/pages/study-archives/StudyArchiveDetailPage')) },
          { path: '/exports', element: load(() => import('@/pages/exports/ExportsPage')) },
          { path: '/templates', element: load(() => import('@/pages/templates/TemplatesPage')) },
          { path: '/learning-plans', element: load(() => import('@/pages/learning-plans/LearningPlansTodoPage')) },
          { path: '/wrongbook', element: load(() => import('@/pages/wrongbook/WrongbookPage')) },
          { path: '/annotations', element: load(() => import('@/pages/annotations/AnnotationsPage')) },
          { path: '/diff', element: load(() => import('@/pages/diff/DiffPage')) },
          { path: '/feedback', element: load(() => import('@/pages/feedback/FeedbackPage')) },
        ],
      },
    ],
  },
])
