import { lazy, Suspense, type ComponentType, type LazyExoticComponent } from 'react'
import { createBrowserRouter, Navigate, Outlet } from 'react-router-dom'
import { RequireAuth } from '@/components/auth/RequireAuth'
import { ManusLayout } from '@/components/layout/ManusLayout'
import { WorkspaceSplitLayout } from '@/components/layout/WorkspaceSplitLayout'
import { LoadingSpinner } from '@/components/shared/LoadingSpinner'
import { NavigationEventHost } from '@/components/shared/NavigationEventHost'
import { getRouteConfigById } from '@/router/routes.config'

const ChatPage = lazy(() => import('@/pages/ChatPage'))
const LoginPage = lazy(() => import('@/pages/auth/LoginPage'))
const BlueprintPage = lazy(() => import('@/pages/BlueprintPage'))
const LessonPlansPage = lazy(() => import('@/pages/LessonPlansPage'))
const LessonPlanDetailPage = lazy(() => import('@/pages/LessonPlanDetailPage'))
const StudyMaterialsPage = lazy(() => import('@/pages/StudyMaterialsPage'))
const KnowledgeVideoPage = lazy(() => import('@/pages/KnowledgeVideoPage'))
const PapersPage = lazy(() => import('@/pages/PapersPage'))
const PaperDetailPage = lazy(() => import('@/pages/PaperDetailPage'))
const CanvasPage = lazy(() => import('@/pages/CanvasPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const QuestionEvaluatePage = lazy(() => import('@/pages/QuestionEvaluatePage'))
const QuestionLibraryPage = lazy(() => import('@/pages/QuestionLibraryPage'))
const AiGeneratePage = lazy(() => import('@/pages/AiGeneratePage'))
const QuestionReviewPage = lazy(() => import('@/features/aiGenerate/QuestionReviewPage'))
const DeepThinkPage = lazy(() => import('@/pages/DeepThinkPage'))
const TaskCenterPage = lazy(() => import('@/pages/TaskCenterPage'))
const SearchPage = lazy(() => import('@/pages/SearchPage'))
const StudyArchiveDetailPage = lazy(() => import('@/pages/StudyArchiveDetailPage'))
const SharePage = lazy(() => import('@/pages/SharePage'))
const ExportsPage = lazy(() => import('@/pages/ExportsPage'))
const TemplatesPage = lazy(() => import('@/pages/TemplatesPage'))
const LearningPlansTodoPage = lazy(() => import('@/pages/LearningPlansTodoPage'))
const WrongbookPage = lazy(() => import('@/pages/WrongbookPage'))
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const AnnotationsPage = lazy(() => import('@/pages/AnnotationsPage'))
const DiffPage = lazy(() => import('@/pages/DiffPage'))
const FeedbackPage = lazy(() => import('@/pages/FeedbackPage'))

function PageLoader() {
  return (
    <div className="flex h-full items-center justify-center">
      <LoadingSpinner size="lg" />
    </div>
  )
}

function load(Component: ComponentType | LazyExoticComponent<ComponentType>) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  )
}

function RootRouteShell() {
  return (
    <>
      <NavigationEventHost />
      <Outlet />
    </>
  )
}

function handle(routeId: string) {
  return { routeConfig: getRouteConfigById(routeId) }
}

export const router = createBrowserRouter([
  {
    element: <RootRouteShell />,
    children: [
      { path: '/login', element: load(LoginPage) },
      { path: '/share/:token', element: load(SharePage) },
      {
        path: '/',
        element: <ManusLayout />,
        children: [
          { index: true, element: <Navigate to="/chat" replace /> },
          {
            element: <RequireAuth />,
            children: [
              { path: 'chat', element: load(ChatPage), handle: handle('chat') },
              { path: 'chat/:conversationId', element: load(ChatPage), handle: handle('chat-detail') },
              { path: 'blueprint', element: load(BlueprintPage), handle: handle('blueprint') },
              {
                path: 'lesson-plans',
                element: <WorkspaceSplitLayout kind="lesson-plans" />,
                handle: handle('lesson-plans'),
                children: [
                  { index: true, element: load(LessonPlansPage), handle: handle('lesson-plans') },
                  { path: ':lessonPlanId', element: load(LessonPlanDetailPage), handle: handle('lesson-plan-detail') },
                ],
              },
              { path: 'study-materials', element: load(StudyMaterialsPage), handle: handle('study-materials') },
              { path: 'knowledge-videos', element: load(KnowledgeVideoPage), handle: handle('knowledge-videos') },
              { path: 'deepthink', element: load(DeepThinkPage), handle: handle('deepthink') },
              { path: 'question-evaluate', element: load(QuestionEvaluatePage), handle: handle('question-evaluate') },
              { path: 'question-library', element: load(QuestionLibraryPage), handle: handle('question-library') },
              {
                path: 'ai-generate',
                element: <WorkspaceSplitLayout kind="ai-generate" />,
                handle: handle('ai-generate'),
                children: [
                  { index: true, element: load(AiGeneratePage), handle: handle('ai-generate') },
                  {
                    path: 'review/:sessionId/:questionId',
                    element: load(QuestionReviewPage),
                    handle: handle('ai-generate-review'),
                  },
                ],
              },
              {
                path: 'papers',
                element: <WorkspaceSplitLayout kind="papers" />,
                handle: handle('papers'),
                children: [
                  { index: true, element: load(PapersPage), handle: handle('papers') },
                  { path: ':paperId', element: load(PaperDetailPage), handle: handle('paper-detail') },
                ],
              },
              { path: 'canvas', element: load(CanvasPage), handle: handle('canvas') },
              { path: 'settings', element: load(SettingsPage), handle: handle('settings') },
              { path: 'tasks', element: load(TaskCenterPage), handle: handle('tasks') },
              { path: 'search', element: load(SearchPage), handle: handle('search') },
              {
                path: 'study-archives',
                element: <WorkspaceSplitLayout kind="study-archives" />,
                children: [
                  { index: true, element: <Navigate to="/study-materials" replace />, handle: handle('study-materials') },
                  {
                    path: ':archiveId',
                    element: load(StudyArchiveDetailPage),
                    handle: handle('study-archive-detail'),
                  },
                ],
              },
              { path: 'exports', element: load(ExportsPage), handle: handle('exports') },
              { path: 'templates', element: load(TemplatesPage), handle: handle('templates') },
              { path: 'learning-plans', element: load(LearningPlansTodoPage), handle: handle('learning-plans') },
              { path: 'wrongbook', element: load(WrongbookPage), handle: handle('wrongbook') },
              { path: 'dashboard', element: load(DashboardPage), handle: handle('dashboard') },
              { path: 'annotations', element: load(AnnotationsPage), handle: handle('annotations') },
              { path: 'diff', element: load(DiffPage), handle: handle('diff') },
              { path: 'feedback', element: load(FeedbackPage), handle: handle('feedback') },
            ],
          },
        ],
      },
    ],
  },
])
