const CACHE_VERSION = 'study-ai-v1'
const APP_SHELL_CACHE = `${CACHE_VERSION}:shell`
const API_CACHE = `${CACHE_VERSION}:api`

const APP_SHELL_URLS = ['/', '/index.html', '/offline.html', '/manifest.webmanifest']
const CACHEABLE_API_PATHS = new Set(['/api/system/config', '/api/conversations'])

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(APP_SHELL_CACHE)
      .then((cache) => cache.addAll(APP_SHELL_URLS))
      .then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith('study-ai-') && !key.startsWith(CACHE_VERSION))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  )
})

function isCacheableApiRequest(url) {
  if (CACHEABLE_API_PATHS.has(url.pathname)) return true
  return url.pathname.startsWith('/api/conversations?')
}

async function networkFirst(request, cacheName, fallbackUrl) {
  const cache = await caches.open(cacheName)
  try {
    const response = await fetch(request)
    if (response.ok) {
      cache.put(request, response.clone())
    }
    return response
  } catch (error) {
    const cached = await cache.match(request)
    if (cached) return cached
    if (fallbackUrl) return caches.match(fallbackUrl)
    throw error
  }
}

async function cacheFirst(request) {
  const cached = await caches.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) {
    const cache = await caches.open(APP_SHELL_CACHE)
    cache.put(request, response.clone())
  }
  return response
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  if (request.mode === 'navigate') {
    event.respondWith(networkFirst(request, APP_SHELL_CACHE, '/offline.html'))
    return
  }

  if (isCacheableApiRequest(url)) {
    event.respondWith(networkFirst(request, API_CACHE))
    return
  }

  if (['script', 'style', 'font', 'image', 'manifest'].includes(request.destination)) {
    event.respondWith(cacheFirst(request))
  }
})
