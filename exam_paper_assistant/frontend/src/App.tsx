import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import RootLayout from "@/layouts/RootLayout";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const BlueprintPage = lazy(() => import("@/pages/BlueprintPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const PapersPage = lazy(() => import("@/pages/PapersPage"));
const PaperDetailPage = lazy(() => import("@/pages/PaperDetailPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));
const LearningCanvasPage = lazy(() => import("@/pages/LearningCanvasPage"));

function PageLoading() {
  return (
    <div className="h-full flex items-center justify-center bg-muted/30">
      <div className="animate-spin rounded-full h-7 w-7 border-b-2 border-primary"></div>
    </div>
  );
}

function App() {
  const fallback = <PageLoading />;
  return (
    <Routes>
      <Route path="/" element={<RootLayout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route
          path="dashboard"
          element={
            <Suspense fallback={fallback}>
              <DashboardPage />
            </Suspense>
          }
        />
        <Route
          path="blueprint"
          element={
            <Suspense fallback={fallback}>
              <BlueprintPage />
            </Suspense>
          }
        />
        <Route
          path="chat/:conversationId?"
          element={
            <Suspense fallback={fallback}>
              <ChatPage />
            </Suspense>
          }
        />
        <Route
          path="learn/:boardId?"
          element={
            <Suspense fallback={fallback}>
              <LearningCanvasPage />
            </Suspense>
          }
        />
        <Route
          path="papers"
          element={
            <Suspense fallback={fallback}>
              <PapersPage />
            </Suspense>
          }
        />
        <Route
          path="papers/:paperId"
          element={
            <Suspense fallback={fallback}>
              <PaperDetailPage />
            </Suspense>
          }
        />
        <Route
          path="settings"
          element={
            <Suspense fallback={fallback}>
              <SettingsPage />
            </Suspense>
          }
        />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  );
}

export default App;
