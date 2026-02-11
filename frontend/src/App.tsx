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
        <Route path="/" element={<ManusLayout />}>
          <Route index element={<Navigate to="/chat" replace />} />
          <Route element={<RequireAuth />}>
            <Route path="chat" element={<ChatPage />} />
            <Route path="chat/:conversationId" element={<ChatPage />} />
          </Route>
          <Route path="blueprint" element={<BlueprintPage />} />
          <Route path="lesson-plans" element={<LessonPlansPage />} />
          <Route path="lesson-plans/:lessonPlanId" element={<LessonPlanDetailPage />} />
          <Route path="study-materials" element={<StudyMaterialsPage />} />
          <Route path="papers" element={<PapersPage />} />
          <Route path="papers/:paperId" element={<PaperDetailPage />} />
          <Route path="canvas" element={<CanvasPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export default App
