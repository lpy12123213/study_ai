type MarkdownTransformer = (segment: string) => string

function isEscaped(value: string, index: number): boolean {
  let slashCount = 0
  for (let i = index - 1; i >= 0 && value[i] === '\\'; i -= 1) {
    slashCount += 1
  }
  return slashCount % 2 === 1
}

function findClosingBackticks(value: string, start: number, marker: string): number {
  return value.indexOf(marker, start + marker.length)
}

function transformOutsideCode(value: string, transform: MarkdownTransformer): string {
  let output = ''
  let plainStart = 0
  let index = 0

  while (index < value.length) {
    if (value.startsWith('```', index) || value.startsWith('~~~', index)) {
      const marker = value.slice(index, index + 3)
      const end = findClosingBackticks(value, index, marker)
      if (end < 0) break

      output += transform(value.slice(plainStart, index))
      output += value.slice(index, end + marker.length)
      index = end + marker.length
      plainStart = index
      continue
    }

    if (value[index] === '`') {
      let markerEnd = index + 1
      while (markerEnd < value.length && value[markerEnd] === '`') markerEnd += 1
      const marker = value.slice(index, markerEnd)
      const end = value.indexOf(marker, markerEnd)
      if (end < 0) break

      output += transform(value.slice(plainStart, index))
      output += value.slice(index, end + marker.length)
      index = end + marker.length
      plainStart = index
      continue
    }

    index += 1
  }

  output += transform(value.slice(plainStart))
  return output
}

function transformStorageMathSegment(segment: string): string {
  let output = ''
  let index = 0

  while (index < segment.length) {
    if (segment.startsWith('\\(', index) && !isEscaped(segment, index)) {
      const end = segment.indexOf('\\)', index + 2)
      if (end >= 0) {
        const latex = segment.slice(index + 2, end)
        if (latex.trim()) {
          output += `$${latex}$`
          index = end + 2
          continue
        }
      }
    }

    if (segment.startsWith('\\[', index) && !isEscaped(segment, index)) {
      const end = segment.indexOf('\\]', index + 2)
      if (end >= 0) {
        const latex = segment.slice(index + 2, end)
        if (latex.trim()) {
          output += `$$${latex}$$`
          index = end + 2
          continue
        }
      }
    }

    output += segment[index]
    index += 1
  }

  return output
}

function looksLikeMathLatex(latex: string): boolean {
  const trimmed = latex.trim()
  if (!trimmed) return false
  if (trimmed !== latex) return false
  if (/^\d+(?:[.,]\d+)?$/.test(trimmed)) return false
  return /[\\^_{}=<>+\-*/]|[A-Za-z]|[\u0370-\u03ff]/.test(trimmed)
}

function transformEditorMathSegment(segment: string): string {
  let output = ''
  let index = 0

  while (index < segment.length) {
    if (segment.startsWith('$$', index) && !isEscaped(segment, index)) {
      const end = segment.indexOf('$$', index + 2)
      if (end >= 0) {
        output += segment.slice(index, end + 2)
        index = end + 2
        continue
      }
    }

    if (segment[index] === '$' && !isEscaped(segment, index)) {
      const end = segment.indexOf('$', index + 1)
      if (end >= 0 && segment[end + 1] !== '$') {
        const latex = segment.slice(index + 1, end)
        if (looksLikeMathLatex(latex)) {
          output += `\\(${latex}\\)`
          index = end + 1
          continue
        }
      }
    }

    output += segment[index]
    index += 1
  }

  return output
}

export function storageMarkdownToEditorMarkdown(value: string): string {
  return transformOutsideCode(value, transformStorageMathSegment)
}

export function editorMarkdownToStorageMarkdown(value: string): string {
  return transformOutsideCode(value, transformEditorMathSegment)
}

export function normalizeStorageMarkdown(value: string): string {
  return editorMarkdownToStorageMarkdown(storageMarkdownToEditorMarkdown(value))
}
