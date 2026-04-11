import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MotionConfig } from 'framer-motion'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'
import { UserSettingsBootstrap } from '@/components/shared/UserSettingsBootstrap'
import { ToastHost } from '@/components/shared/ToastHost'
import { NavigationEventHost } from '@/components/shared/NavigationEventHost'
import { useUiPreferencesStore } from '@/stores/useUiPreferencesStore'
import App from './App'
import './index.css'
import 'katex/dist/katex.min.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1,
    },
  },
})

function RootApp() {
  const reduceMotion = useUiPreferencesStore((s) => s.reduceMotion)
  return (
    <MotionConfig reducedMotion={reduceMotion ? 'always' : 'user'}>
      <UserSettingsBootstrap />
      <BrowserRouter>
        <NavigationEventHost />
        <ToastHost />
        <App />
      </BrowserRouter>
    </MotionConfig>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <RootApp />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
