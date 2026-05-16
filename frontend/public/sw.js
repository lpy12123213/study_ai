// Bump CACHE_VERSION on every release to invalidate old caches.
const CACHE_VERSION = 'study-ai-v2'
const APP_SHELL_CACHE = `${CACHE_VERSION}:shell`
const ASSET_CACHE = `${CACHE_VERSION}:assets`
const API_CACHE = `${CACHE_VERSION}:api`

const APP_SHELL_URLS = ['/offline.html', '/manifest.webmanifest']
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

// Hashed assets like /assets/index-abc123.js are content-addressed and safe to cache long-term.
function isHashedAsset(url) {
  return /\/assets\/.+-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$/.test(url.pathname)
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

async function cacheFirstHashed(request) {
  const cache = await caches.open(ASSET_CACHE)
  const cached = await cache.match(request)
  if (cached) return cached
  const response = await fetch(request)
  if (response.ok) {
    cache.put(request, response.clone())
  }
  return response
}

self.addEventListener('fetch', (event) => {
  const { request } = event
  if (request.method !== 'GET') return

  const url = new URL(request.url)
  if (url.origin !== self.location.origin) return

  // Always go to network for navigation (HTML). This ensures users get the
  // latest index.html which references the latest hashed asset bundles.
  if (request.mode === 'navigate' || request.destination === 'document') {
    event.respondWith(networkFirst(request, APP_SHELL_CACHE, '/offline.html'))
    return
  }

  if (isCacheableApiRequest(url)) {
    event.respondWith(networkFirst(request, API_CACHE))
    return
  }

  // Only cache-first for hashed/fingerprinted assets (immutable).
  // Non-hashed scripts/styles use network-first so users see updates without Shift+F5.
  if (['script', 'style', 'font', 'image', 'manifest'].includes(request.destination)) {
    if (isHashedAsset(url)) {
      event.respondWith(cacheFirstHashed(request))
    } else {
      event.respondWith(networkFirst(request, ASSET_CACHE))
    }
  }
})

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting()
  }
})
