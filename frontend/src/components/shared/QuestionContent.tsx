import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import katex from 'katex'
import { AuthImage } from '@/components/shared/AuthImage'
import { cn } from '@/lib/utils'

function isProbablyVerticalText(value: string): boolean {
  const text = String(value || '')
  if (!/[\r\n\u2028\u2029]/.test(text)) return false

  const lines = text
    .split(/\r\n|\r|\n|\u2028|\u2029/)
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
    return ratio2 >= 0.6 || (ratio3 >= 0.7 && short2 >= 10)
  }

  return ratio2 >= 0.55 || (ratio3 >= 0.7 && short2 >= 6)
}

function normalizeQuestionText(input: string): string {
  const raw = String(input || '')
  if (!isProbablyVerticalText(raw)) return raw

  // Typical crawler failure mode: content is split by newlines between inline nodes.
  // Re-join the non-empty fragments while preserving intentional paragraph breaks.
  const parts = raw.split(/\r\n|\r|\n|\u2028|\u2029/)
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

function stripMathWrappers(value: string): string {
  let token = String(value || '').trim()
  while (true) {
    let next = token
    if (next.startsWith('\\(') && next.endsWith('\\)') && next.length >= 4) {
      next = next.slice(2, -2).trim()
    } else if (next.startsWith('\\[') && next.endsWith('\\]') && next.length >= 4) {
      next = next.slice(2, -2).trim()
    } else if (next.startsWith('$$') && next.endsWith('$$') && next.length >= 4) {
      next = next.slice(2, -2).trim()
    } else if (next.startsWith('$') && next.endsWith('$') && next.length >= 2) {
      next = next.slice(1, -1).trim()
    }
    if (next === token) return token
    token = next
  }
}

function normalizeTableToken(value: string): string {
  const token = stripMathWrappers(value).replace(/\s+/g, ' ').trim()
  if (token === '...' || token === '…') return '\\cdots'
  return token
}

function looksLikeValueToken(value: string): boolean {
  const token = normalizeTableToken(value)
  if (!token) return false
  if (['\\cdots', '\\ldots'].includes(token)) return true
  if (/^-?\d+(\.\d+)?$/.test(token)) return true
  if (/^[a-zA-Z]$/.test(token)) return true
  if (/^[a-zA-Z]_\d+$/.test(token)) return true
  return ['ξ', '\\xi', 'n', 'm', 'k'].includes(token)
}

function looksLikeProbToken(value: string): boolean {
  const token = normalizeTableToken(value)
  if (!token) return false
  if (['\\cdots', '\\ldots'].includes(token)) return true
  if (/^[pqPQ]_\d+$/.test(token)) return true
  if (/^[pqPQ]_[a-zA-Z0-9]+$/.test(token)) return true
  return ['P', 'p', 'p_n', 'q_n'].includes(token)
}

function looksLikeGenericHeaderToken(value: string): boolean {
  const token = normalizeTableToken(value)
  if (!token) return false
  if (/\d/.test(token)) return false
  return token.length <= 16
}

function looksLikeGenericValueToken(value: string): boolean {
  const token = normalizeTableToken(value)
  if (!token) return false
  if (['\\cdots', '\\ldots'].includes(token)) return true
  if (/^-?\d+(\.\d+)?(次|个|人|项|分|天|%|cm|m|kg)?$/.test(token)) return true
  if (/^-?\d+\/\d+$/.test(token)) return true
  return token.startsWith('\\frac{')
}

function matchGenericMatrix(
  paragraphs: string[],
  index: number
): { prefixLines: string[]; matrixRows: string[][]; nextIndex: number } | null {
  const lines = paragraphs[index].split('\n').map((line) => line.trim()).filter(Boolean)
  if (lines.length < 3) return null

  for (let offset = 0; offset <= lines.length - 3; offset += 1) {
    const headerRow = lines.slice(offset)
    if (headerRow.length < 3 || !headerRow.every(looksLikeGenericHeaderToken)) continue

    const matrixRows: string[][] = [headerRow]
    let nextIndex = index + 1
    while (nextIndex < paragraphs.length) {
      const row = paragraphs[nextIndex].split('\n').map((line) => line.trim()).filter(Boolean)
      if (
        row.length === headerRow.length &&
        looksLikeGenericHeaderToken(row[0] || '') &&
        row.slice(1).every(looksLikeGenericValueToken)
      ) {
        matrixRows.push(row)
        nextIndex += 1
        continue
      }
      break
    }

    if (matrixRows.length >= 3) {
      return {
        prefixLines: lines.slice(0, offset),
        matrixRows,
        nextIndex,
      }
    }
  }

  return null
}

function repairBrokenTableBlocks(input: string): string {
  const raw = String(input || '').replace(/\r\n?/g, '\n')
  if (!raw.trim()) return raw

  const paragraphs = raw
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean)

  if (paragraphs.length < 2) return raw

  let changed = false
  const rebuilt: string[] = []

  for (let index = 0; index < paragraphs.length; index += 1) {
    const first = paragraphs[index]
    const second = paragraphs[index + 1]
    if (first && second) {
      const rowA = first.split('\n').map((line) => line.trim()).filter(Boolean)
      const rowB = second.split('\n').map((line) => line.trim()).filter(Boolean)
      const headerA = normalizeTableToken(rowA[0] || '').toLowerCase()
      const headerB = normalizeTableToken(rowB[0] || '')
      if (
        rowA.length >= 4 &&
        rowB.length >= 4 &&
        ['ξ', '\\xi', 'xi'].includes(headerA) &&
        ['P', 'p'].includes(headerB) &&
        Math.abs(rowA.length - rowB.length) <= 1 &&
        rowA.slice(1).every(looksLikeValueToken) &&
        rowB.slice(1).every(looksLikeProbToken)
      ) {
        const width = Math.max(rowA.length, rowB.length)
        const cellsA = [...rowA.map(normalizeTableToken), ...Array.from({ length: width - rowA.length }, () => '')]
        const cellsB = [...rowB.map(normalizeTableToken), ...Array.from({ length: width - rowB.length }, () => '')]
        rebuilt.push(`$$\\begin{array}{${'c'.repeat(Math.max(2, width))}}${cellsA.join(' & ')} \\\\ ${cellsB.join(' & ')}\\end{array}$$`)
        changed = true
        index += 1
        continue
      }
    }

    if (first) {
      const genericMatrix = matchGenericMatrix(paragraphs, index)
      if (genericMatrix) {
        const { prefixLines, matrixRows, nextIndex } = genericMatrix
        if (prefixLines.length > 0) {
          rebuilt.push(prefixLines.join('\n'))
        }
        const width = Math.max(...matrixRows.map((row) => row.length))
        const latexRows = matrixRows.map((row) => {
          const normalized = row.map(normalizeTableToken)
          return [...normalized, ...Array.from({ length: width - normalized.length }, () => '')].join(' & ')
        })
        rebuilt.push(`$$\\begin{array}{${'c'.repeat(Math.max(2, width))}}${latexRows.join(' \\\\ ')}\\end{array}$$`)
        changed = true
        index = nextIndex - 1
        continue
      }
    }

    rebuilt.push(first)
  }

  if (!changed) return raw
  return rebuilt.join('\n\n')
}

function KatexRender(props: { latex: string; displayMode: boolean }) {
  const { latex, displayMode } = props
  const containerRef = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const src = String(latex || '').trim()
    if (!src) {
      el.textContent = ''
      return
    }

    try {
      // Avoid `dangerouslySetInnerHTML`: render via KaTeX DOM APIs and keep trust disabled.
      el.textContent = ''
      katex.render(src, el, {
        displayMode,
        throwOnError: false,
        strict: 'ignore',
        trust: false,
      })
    } catch {
      el.textContent = displayMode ? `\\[${src}\\]` : `\\(${src}\\)`
    }
  }, [latex, displayMode])

  return <span ref={containerRef} className={displayMode ? 'block my-2 overflow-x-auto' : 'inline'} />
}

function renderKatex(latex: string, displayMode: boolean): ReactNode {
  const src = String(latex || '').trim()
  if (!src) return null
  return <KatexRender latex={src} displayMode={displayMode} />
}

export function QuestionContent(props: { content: string; className?: string }) {
  const { content, className } = props

  const nodes = useMemo(() => {
    const text = normalizeQuestionText(repairBrokenTableBlocks(String(content || '')))
    if (!text) return [] as ReactNode[]

    // Tokens:
    // - [图片:https://...]
    // - \( ... \)  (inline math)
    // - \[ ... \]  (display math)
    // - $ ... $    (inline math)
    // - $$ ... $$  (display math)
    const tokenRe =
      /(\[图片(?::([^\]]+))?\])|(\\\[([\s\S]*?)\\\])|(\\\(([\s\S]*?)\\\))|(\$\$([\s\S]*?)\$\$)|(\$([^\n$]*?)\$)/g

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
                <AuthImage
                  src={url}
                  alt="题目图片"
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
      } else if (match[7]) {
        const latex = match[8] || ''
        out.push(<span key={`math:block2:${index}`}>{renderKatex(latex, true)}</span>)
      } else if (match[9]) {
        const latex = match[10] || ''
        out.push(<span key={`math:inline2:${index}`}>{renderKatex(latex, false)}</span>)
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

