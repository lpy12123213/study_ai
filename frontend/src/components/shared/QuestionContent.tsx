import { useMemo, type ReactNode } from 'react'
import katex from 'katex'
import { cn } from '@/lib/utils'

function isProbablyVerticalText(value: string): boolean {
  const text = String(value || '')
  if (!text.includes('\n')) return false

  const lines = text
    .split(/\r?\n/)
    .map((l) => l.trim())
    .filter((l) => l)

  // Two common failure modes:
  // 1) truly "vertical": nearly every line is 1-2 chars (one character per line).
  // 2) "fragmented": many short lines (e.g. E / F / AB / 交 / 于) that should be inline.
  if (lines.length < 8) return false

  let short2 = 0
  let short3 = 0
  for (const line of lines) {
    if (line.length <= 2) short2 += 1
    if (line.length <= 3) short3 += 1
  }

  const ratio2 = short2 / lines.length
  const ratio3 = short3 / lines.length

  if (lines.length >= 25) {
    return ratio2 >= 0.7
  }

  return ratio2 >= 0.55 || (ratio3 >= 0.7 && short2 >= 6)
}

function normalizeQuestionText(input: string): string {
  const raw = String(input || '')
  if (!isProbablyVerticalText(raw)) return raw

  // Typical crawler failure mode: content is split by newlines between inline nodes.
  // Re-join the non-empty fragments while preserving intentional paragraph breaks.
  const parts = raw.split(/\r?\n/)
  let out = ''
  let pendingParagraphBreak = false

  for (const line of parts) {
    const t = line.trim()
    if (!t) {
      pendingParagraphBreak = true
      continue
    }

    if (pendingParagraphBreak && out) out += '\n\n'
    pendingParagraphBreak = false
    out += t
  }

  return out
}

function renderKatex(latex: string, displayMode: boolean): ReactNode {
  const src = String(latex || '').trim()
  if (!src) return null
  try {
    const html = katex.renderToString(src, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
    })
    return (
      <span
        className={displayMode ? 'block my-2 overflow-x-auto' : 'inline'}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  } catch {
    return displayMode ? `\\[${src}\\]` : `\\(${src}\\)`
  }
}

export function QuestionContent(props: { content: string; className?: string }) {
  const { content, className } = props

  const nodes = useMemo(() => {
    const text = normalizeQuestionText(String(content || ''))
    if (!text) return [] as ReactNode[]

    // Tokens:
    // - [图片:https://...]
    // - \( ... \)  (inline math)
    // - \[ ... \]  (display math)
    const tokenRe = /(\[图片(?::([^\]]+))?\])|(\\\[([\s\S]*?)\\\])|(\\\(([\s\S]*?)\\\))/g

    const out: ReactNode[] = []
    let lastIndex = 0
    let match: RegExpExecArray | null

    while ((match = tokenRe.exec(text)) !== null) {
      const index = match.index ?? 0
      if (index > lastIndex) {
        out.push(text.slice(lastIndex, index))
      }

      if (match[1]) {
        const url = String(match[2] || '').trim()
        if (!url) {
          out.push('[图片]')
        } else {
          out.push(
            <div key={`img:${index}`} className="my-2">
              <a href={url} target="_blank" rel="noreferrer" className="inline-block">
                <img
                  src={url}
                  alt="题目图片"
                  loading="lazy"
                  className="max-w-full max-h-[360px] object-contain rounded-md border bg-white"
                />
              </a>
            </div>
          )
        }
      } else if (match[3]) {
        const latex = match[4] || ''
        out.push(<span key={`math:block:${index}`}>{renderKatex(latex, true)}</span>)
      } else if (match[5]) {
        const latex = match[6] || ''
        out.push(<span key={`math:inline:${index}`}>{renderKatex(latex, false)}</span>)
      }

      lastIndex = index + match[0].length
    }

    if (lastIndex < text.length) {
      out.push(text.slice(lastIndex))
    }

    return out
  }, [content])

  if (!content?.trim()) return null

  return (
    <div className={cn('whitespace-pre-wrap leading-relaxed break-words', className)}>
      {nodes}
    </div>
  )
}

