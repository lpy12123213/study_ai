export function registerStudyAiServiceWorker(): void {
  if (import.meta.env.MODE === 'test') return
  if (!('serviceWorker' in navigator)) return

  // In development mode, unregister any existing service worker to avoid stale caches.
  // The service worker aggressively caches assets which causes "needs Shift+F5 to see changes"
  // problems during development.
  if (import.meta.env.DEV) {
    navigator.serviceWorker.getRegistrations().then((registrations) => {
      for (const registration of registrations) {
        registration.unregister().catch(() => {
          // ignore
        })
      }
    }).catch(() => {
      // ignore
    })
    // Also clear any existing caches
    if ('caches' in self) {
      caches.keys().then((keys) => {
        for (const key of keys) {
          if (key.startsWith('study-ai-')) {
            caches.delete(key).catch(() => {
              // ignore
            })
          }
        }
      }).catch(() => {
        // ignore
      })
    }
    return
  }

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((error: unknown) => {
      console.warn('pwa_service_worker_registration_failed', error)
    })
  })
}
