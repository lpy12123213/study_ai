export function registerStudyAiServiceWorker(): void {
  if (import.meta.env.MODE === 'test') return
  if (!('serviceWorker' in navigator)) return

  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch((error: unknown) => {
      console.warn('pwa_service_worker_registration_failed', error)
    })
  })
}
