import { useEffect, useMemo, useState, type MouseEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { downloadObjectUrl, resolveApiResourceUrl } from '@/api/client'

function isAbsoluteUrl(href: string): boolean {
  return /^https?:\/\//i.test(href)
}

function isApiResource(href: string): boolean {
  const value = String(href || '').trim()
  if (value.startsWith('/api/') || value.startsWith('api/')) return true
  if (isAbsoluteUrl(value)) {
    try {
      const u = new URL(value)
      return String(u.pathname || '').startsWith('/api/')
    } catch {
      return false
    }
  }
  return false
}

function isGeneratedMedia(href: string): boolean {
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

function linkClassName(href: string): string {
  const url = String(href || '')
  const isDownload = isGeneratedMedia(url) && /\.(md|pdf|tex|zip|png|jpg|jpeg|webp)$/i.test(url)
  return isDownload
    ? 'inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground no-underline hover:bg-primary/90'
    : 'text-primary underline underline-offset-4 hover:opacity-90'
}

function AuthImage(props: { src?: string; alt?: string; className?: string }) {
  const rawSrc = String(props.src || '').trim()
  const resolved = useMemo(() => (rawSrc ? resolveApiResourceUrl(rawSrc) : ''), [rawSrc])
  const [objectUrl, setObjectUrl] = useState<string>('')

  useEffect(() => {
    if (!rawSrc || !isGeneratedMedia(rawSrc)) {
      setObjectUrl('')
      return
    }
    let active = true
    let revoke = () => {}

    downloadObjectUrl(rawSrc)
      .then((r) => {
        revoke = r.revoke
        if (!active) {
          revoke()
          return
        }
        setObjectUrl(r.objectUrl)
      })
      .catch(() => {
        if (!active) return
        setObjectUrl('')
      })

    return () => {
      active = false
      revoke()
    }
  }, [rawSrc])

  return (
    <img src={objectUrl || resolved} alt={props.alt || ''} className={props.className} loading="lazy" />
  )
}

export function SecureMarkdown(props: { markdown: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      components={{
        a: ({ href, children, ...anchorProps }) => {
          const rawHref = typeof href === 'string' ? href : ''
          const resolved = rawHref ? resolveApiResourceUrl(rawHref) : ''
          const external = isAbsoluteUrl(rawHref) && !isApiResource(rawHref)

          const onClick = async (e: MouseEvent<HTMLAnchorElement>) => {
            if (!rawHref) return
            if (!isGeneratedMedia(rawHref)) return
            e.preventDefault()
            const { objectUrl, revoke } = await downloadObjectUrl(rawHref)
            const win = window.open(objectUrl, '_blank', 'noopener,noreferrer')
            if (!win) {
              // Popup blocked: best-effort download.
              const a = document.createElement('a')
              a.href = objectUrl
              a.download = ''
              a.click()
            }
            window.setTimeout(revoke, 60_000)
          }

          return (
            <a
              href={resolved || rawHref}
              className={linkClassName(rawHref)}
              target={external ? '_blank' : undefined}
              rel={external ? 'noopener noreferrer' : undefined}
              onClick={onClick}
              {...anchorProps}
            >
              {children}
            </a>
          )
        },
        img: ({ src, alt, ...imgProps }) => {
          const rawSrc = typeof src === 'string' ? src : ''
          return <AuthImage src={rawSrc} alt={alt} className={(imgProps as any).className} />
        },
      }}
    >
      {props.markdown}
    </ReactMarkdown>
  )
}
