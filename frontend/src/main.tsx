import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MotionConfig } from 'framer-motion'
import { QueryProvider } from '@/components/QueryProvider'
import { ErrorBoundary } from '@/components/shared/ErrorBoundary'
import { UserSettingsBootstrap } from '@/components/shared/UserSettingsBootstrap'
import { I18nProvider } from '@/i18n'
import { useUiPreferencesStore } from '@/stores/useUiPreferencesStore'
import App from './App'
import './index.css'
import { registerStudyAiServiceWorker } from './pwa'

function RootApp() {
  const reduceMotion = useUiPreferencesStore((s) => s.reduceMotion)
  return (
    <MotionConfig reducedMotion={reduceMotion ? 'always' : 'user'}>
      <UserSettingsBootstrap />
      <App />
    </MotionConfig>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryProvider>
        <I18nProvider>
          <RootApp />
        </I18nProvider>
      </QueryProvider>
    </ErrorBoundary>
  </StrictMode>,
)

registerStudyAiServiceWorker()
