import { memo, type MouseEvent } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

import { downloadObjectUrl, resolveApiResourceUrl } from '@/api/client'
import { AuthImage, isGeneratedMediaResource } from '@/components/shared/AuthImage'
import { cn } from '@/lib/utils'

const REMARK_PLUGINS = [remarkGfm, remarkMath]
const REHYPE_PLUGINS = [rehypeKatex]
const DEFAULT_MARKDOWN_CLASS = 'aurora-markdown prose prose-sm dark:prose-invert max-w-none'

export type MarkdownProps = {
  markdown?: string
  content?: string
  className?: string
  components?: Components
}

function markdownContent(props: Pick<MarkdownProps, 'markdown' | 'content'>): string {
  return props.markdown ?? props.content ?? ''
}

function normalizeMathDelimiters(markdown: string): string {
  return String(markdown || '')
    .replace(/\\\[([\s\S]*?)\\\]/g, (_match, body: string) => `\n\n$$\n${body}\n$$\n\n`)
    .replace(/\\\(([\s\S]*?)\\\)/g, (_match, body: string) => `$${body}$`)
}

function isAbsoluteUrl(href: string): boolean {
  return /^https?:\/\//i.test(href)
}

function isApiResource(href: string): boolean {
  const value = String(href || '').trim()
  if (value.startsWith('/api/') || value.startsWith('api/')) return true
  if (!isAbsoluteUrl(value)) return false

  try {
    const url = new URL(value)
    return String(url.pathname || '').startsWith('/api/')
  } catch {
    return false
  }
}

function linkClassName(href: string): string {
  const url = String(href || '')
  const isDownload = isGeneratedMediaResource(url) && /\.(md|pdf|tex|zip|png|jpg|jpeg|webp)$/i.test(url)
  return isDownload
    ? 'aurora-markdown-download-link inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground no-underline hover:bg-primary/90'
    : 'aurora-markdown-link text-primary underline underline-offset-4 hover:opacity-90'
}

const secureComponents: Components = {
  a: ({ href, children, title }) => {
    const rawHref = typeof href === 'string' ? href : ''
    const resolved = rawHref ? resolveApiResourceUrl(rawHref) : ''
    const external = isAbsoluteUrl(rawHref) && !isApiResource(rawHref)

    const onClick = async (event: MouseEvent<HTMLAnchorElement>) => {
      if (!rawHref || !isGeneratedMediaResource(rawHref)) return

      event.preventDefault()
      const { objectUrl, revoke } = await downloadObjectUrl(rawHref)
      const win = window.open(objectUrl, '_blank', 'noopener,noreferrer')
      if (!win) {
        const anchor = document.createElement('a')
        anchor.href = objectUrl
        anchor.download = ''
        anchor.click()
      }
      window.setTimeout(revoke, 60_000)
    }

    return (
      <a
        href={resolved || rawHref}
        className={linkClassName(rawHref)}
        target={external ? '_blank' : undefined}
        rel={external ? 'noopener noreferrer' : undefined}
        title={title}
        onClick={onClick}
      >
        {children}
      </a>
    )
  },
  img: ({ src, alt, className }) => {
    const rawSrc = typeof src === 'string' ? src : ''
    return <AuthImage src={rawSrc} alt={alt} className={cn('aurora-markdown-image', typeof className === 'string' ? className : undefined)} />
  },
}

function MarkdownView(props: MarkdownProps) {
  return (
    <div className={cn(DEFAULT_MARKDOWN_CLASS, props.className)}>
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={{ ...secureComponents, ...props.components }}
      >
        {normalizeMathDelimiters(markdownContent(props))}
      </ReactMarkdown>
    </div>
  )
}

function MarkdownUnsafeView(props: MarkdownProps) {
  return (
    <div className={cn(DEFAULT_MARKDOWN_CLASS, props.className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} components={props.components}>
        {normalizeMathDelimiters(markdownContent(props))}
      </ReactMarkdown>
    </div>
  )
}

export const Markdown = memo(
  MarkdownView,
  (prev, next) =>
    markdownContent(prev) === markdownContent(next) &&
    prev.className === next.className &&
    prev.components === next.components
)

export const MarkdownUnsafe = memo(
  MarkdownUnsafeView,
  (prev, next) =>
    markdownContent(prev) === markdownContent(next) &&
    prev.className === next.className &&
    prev.components === next.components
)

export default Markdown
