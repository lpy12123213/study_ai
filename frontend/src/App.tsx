import { Suspense, lazy } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { RequireAuth } from '@/components/auth/RequireAuth'
import { ManusLayout } from '@/components/layout/ManusLayout'
import { LoadingSpinner } from '@/components/shared/LoadingSpinner'

// Lazy load pages
const ChatPage = lazy(() => import('@/pages/ChatPage'))
const BlueprintPage = lazy(() => import('@/pages/BlueprintPage'))
const LessonPlansPage = lazy(() => import('@/pages/LessonPlansPage'))
const LessonPlanDetailPage = lazy(() => import('@/pages/LessonPlanDetailPage'))
const StudyMaterialsPage = lazy(() => import('@/pages/StudyMaterialsPage'))
const PapersPage = lazy(() => import('@/pages/PapersPage'))
const PaperDetailPage = lazy(() => import('@/pages/PaperDetailPage'))
const CanvasPage = lazy(() => import('@/pages/CanvasPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const LoginPage = lazy(() => import('@/pages/LoginPage'))
const QuestionEvaluatePage = lazy(() => import('@/pages/QuestionEvaluatePage'))
const QuestionLibraryPage = lazy(() => import('@/pages/QuestionLibraryPage'))
const AiGeneratePage = lazy(() => import('@/pages/AiGeneratePage'))
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
    <div className="flex items-center justify-center h-full">
      <LoadingSpinner size="lg" />
    </div>
  )
}

function App() {
  return (
    <Suspense fallback={<PageLoader />}> 
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/share/:token" element={<SharePage />} />
        <Route path="/" element={<ManusLayout />}> 
          <Route index element={<Navigate to="/chat" replace />} />
          <Route element={<RequireAuth />}> 
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
            <Route path="blueprint" element={<BlueprintPage />} />
            <Route path="lesson-plans" element={<LessonPlansPage />} />
            <Route path="lesson-plans/:lessonPlanId" element={<LessonPlanDetailPage />} />
            <Route path="study-materials" element={<StudyMaterialsPage />} />
            <Route path="deepthink" element={<DeepThinkPage />} />
            <Route path="question-evaluate" element={<QuestionEvaluatePage />} />
            <Route path="question-library" element={<QuestionLibraryPage />} />
            <Route path="ai-generate" element={<AiGeneratePage />} />
            <Route path="papers" element={<PapersPage />} />
            <Route path="papers/:paperId" element={<PaperDetailPage />} />
            <Route path="canvas" element={<CanvasPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="tasks" element={<TaskCenterPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="study-archives/:archiveId" element={<StudyArchiveDetailPage />} />
            <Route path="exports" element={<ExportsPage />} />
            <Route path="templates" element={<TemplatesPage />} />
            <Route path="learning-plans" element={<LearningPlansTodoPage />} />
            <Route path="wrongbook" element={<WrongbookPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="annotations" element={<AnnotationsPage />} />
            <Route path="diff" element={<DiffPage />} />
            <Route path="feedback" element={<FeedbackPage />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  )
}

export default App
