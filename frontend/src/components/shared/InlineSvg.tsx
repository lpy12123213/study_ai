import { useEffect, useRef, useState } from 'react'
import { downloadObjectUrl } from '@/api/client'
import { isGeneratedMediaResource } from './AuthImage'

interface InlineSvgProps {
  src: string
  /** Optional caption rendered below the SVG. */
  caption?: string
  /** Optional className applied to the wrapper. */
  className?: string
  /** Tabindex on the wrapper for keyboard accessibility. Default 0. */
  tabIndex?: number
  /** aria-label for the figure. */
  ariaLabel?: string
}

const SVG_TAG_RE = /<svg[\s\S]*?<\/svg>/i

/**
 * Fetches an SVG resource (using authenticated client for /api/media/generated/...)
 * and renders it inline as <svg>, enabling CSS / DOM interactions.
 *
 * Falls back to <img> if the response is not SVG or fetching fails.
 */
export function InlineSvg(props: InlineSvgProps) {
  const { src, caption, className, tabIndex = 0, ariaLabel } = props
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const [svgMarkup, setSvgMarkup] = useState<string>('')
  const [errored, setErrored] = useState(false)

  useEffect(() => {
    if (!src) {
      setSvgMarkup('')
      setErrored(false)
      return
    }
    let active = true
    let revoke = () => {}

    async function load() {
      try {
        const requiresAuth = isGeneratedMediaResource(src)
        let text: string
        if (requiresAuth) {
          const result = await downloadObjectUrl(src)
          revoke = result.revoke
          const resp = await fetch(result.objectUrl)
          text = await resp.text()
        } else {
          const resp = await fetch(src, { credentials: 'omit' })
          if (!resp.ok) throw new Error(`fetch ${resp.status}`)
          text = await resp.text()
        }
        if (!active) return
        // Extract a clean <svg>...</svg> body; refuse non-SVG payloads.
        const match = text.match(SVG_TAG_RE)
        if (!match) {
          setErrored(true)
          return
        }
        // Strip any embedded <script> tags as a defense-in-depth sanitization step.
        // (The content originates from our own renderer pipeline, but defensive nonetheless.)
        const cleaned = match[0].replace(/<script[\s\S]*?<\/script>/gi, '')
        setSvgMarkup(cleaned)
      } catch {
        if (active) setErrored(true)
      }
    }

    load()
    return () => {
      active = false
      revoke()
    }
  }, [src])

  if (errored) {
    return (
      <figure className={['inline-svg-fallback', className || ''].filter(Boolean).join(' ')}>
        <img
          src={src}
          alt={ariaLabel || caption || ''}
          className="max-w-full h-auto"
          loading="lazy"
        />
        {caption && <figcaption className="text-xs text-muted-foreground mt-1">{caption}</figcaption>}
      </figure>
    )
  }

  return (
    <figure
      className={['inline-svg', className || ''].filter(Boolean).join(' ')}
      role="figure"
      aria-label={ariaLabel || caption || undefined}
    >
      <div
        ref={wrapperRef}
        tabIndex={tabIndex}
        className="inline-svg-content focus:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded"
        // SVG markup is from our own /api/media/generated namespace + script-stripped.
        dangerouslySetInnerHTML={{ __html: svgMarkup }}
      />
      {caption && <figcaption className="text-xs text-muted-foreground mt-1">{caption}</figcaption>}
    </figure>
  )
}
