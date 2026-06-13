import { useEffect, useMemo, useState } from 'react'
import { downloadObjectUrl, resolveApiResourceUrl } from '@/api/client'
import { ImageOff, RefreshCw } from 'lucide-react'

function isAbsoluteUrl(href: string): boolean {
  return /^https?:\/\//i.test(href)
}

export function isGeneratedMediaResource(href: string): boolean {
  const value = String(href || '').trim()
  if (value.startsWith('/api/media/') || value.startsWith('api/media/')) return true
  if (isAbsoluteUrl(value)) {
    try {
      const u = new URL(value)
      return String(u.pathname || '').startsWith('/api/media/')
    } catch {
      return false
    }
  }
  return false
}

type LoadState = 'idle' | 'loading' | 'loaded' | 'error'

interface AuthImageProps {
  src?: string
  alt?: string
  className?: string
  /** Override the default error fallback. */
  fallback?: React.ReactNode
}

export function AuthImage(props: AuthImageProps) {
  const rawSrc = String(props.src || '').trim()
  const resolved = useMemo(() => (rawSrc ? resolveApiResourceUrl(rawSrc) : ''), [rawSrc])
  const requiresAuthenticatedFetch = isGeneratedMediaResource(rawSrc)
  const [objectUrl, setObjectUrl] = useState<string>('')
  const [state, setState] = useState<LoadState>('idle')
  const [retryNonce, setRetryNonce] = useState(0)

  useEffect(() => {
    if (!rawSrc) {
      setObjectUrl('')
      setState('idle')
      return
    }
    if (!requiresAuthenticatedFetch) {
      // For external URLs, leave state management to the <img> onLoad/onError handlers below.
      setObjectUrl('')
      setState('loading')
      return
    }

    let active = true
    let revoke = () => {}

    setState('loading')
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
        setState('error')
      })

    return () => {
      active = false
      revoke()
    }
  }, [rawSrc, requiresAuthenticatedFetch, retryNonce])

  const src = requiresAuthenticatedFetch ? objectUrl || undefined : resolved || undefined

  if (state === 'error') {
    if (props.fallback !== undefined) return <>{props.fallback}</>
    return (
      <span
        role="img"
        aria-label={props.alt || 'image failed to load'}
        className={[
          'aurora-auth-image-fallback inline-flex flex-col items-center justify-center gap-1 px-3 py-4',
          'border border-dashed border-border/60 bg-muted/40 text-muted-foreground text-xs rounded',
          props.className || '',
        ]
          .filter(Boolean)
          .join(' ')}
        style={{ minWidth: '8rem', minHeight: '5rem' }}
      >
        <ImageOff className="h-4 w-4" aria-hidden="true" />
        <span className="truncate max-w-[14rem]">图片加载失败</span>
        {props.alt && <span className="truncate max-w-[14rem] text-muted-foreground/70">{props.alt}</span>}
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault()
            e.stopPropagation()
            setState('loading')
            setRetryNonce((n) => n + 1)
          }}
          className="aurora-auth-image-retry mt-1 inline-flex items-center gap-1 text-foreground/70 hover:text-foreground"
        >
          <RefreshCw className="h-3 w-3" aria-hidden="true" />
          重试
        </button>
      </span>
    )
  }

  return (
    <img
      src={src}
      alt={props.alt || ''}
      className={['aurora-auth-image', props.className || ''].filter(Boolean).join(' ')}
      loading="lazy"
      onLoad={() => setState('loaded')}
      onError={() => setState('error')}
    />
  )
}
