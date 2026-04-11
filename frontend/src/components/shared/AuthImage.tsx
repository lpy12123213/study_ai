import { useEffect, useMemo, useState } from 'react'
import { downloadObjectUrl, resolveApiResourceUrl } from '@/api/client'

function isAbsoluteUrl(href: string): boolean {
  return /^https?:\/\//i.test(href)
}

export function isGeneratedMediaResource(href: string): boolean {
  const value = String(href || '').trim()
  if (value.startsWith('/api/media/generated/') || value.startsWith('api/media/generated/')) return true
  if (isAbsoluteUrl(value)) {
    try {
      const u = new URL(value)
      return String(u.pathname || '').startsWith('/api/media/generated/')
    } catch {
      return false
    }
  }
  return false
}

export function AuthImage(props: { src?: string; alt?: string; className?: string }) {
  const rawSrc = String(props.src || '').trim()
  const resolved = useMemo(() => (rawSrc ? resolveApiResourceUrl(rawSrc) : ''), [rawSrc])
  const requiresAuthenticatedFetch = isGeneratedMediaResource(rawSrc)
  const [objectUrl, setObjectUrl] = useState<string>('')

  useEffect(() => {
    if (!rawSrc || !requiresAuthenticatedFetch) {
      setObjectUrl('')
      return
    }

    let active = true
    let revoke = () => {}

    downloadObjectUrl(rawSrc)
      .then((result) => {
        revoke = result.revoke
        if (!active) {
          revoke()
          return
        }
        setObjectUrl(result.objectUrl)
      })
      .catch(() => {
        if (!active) return
        setObjectUrl('')
      })

    return () => {
      active = false
      revoke()
    }
  }, [rawSrc, requiresAuthenticatedFetch])

  const src = requiresAuthenticatedFetch ? objectUrl || undefined : resolved || undefined
  return <img src={src} alt={props.alt || ''} className={props.className} loading="lazy" />
}
