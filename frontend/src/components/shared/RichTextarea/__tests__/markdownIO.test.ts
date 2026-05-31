import { describe, expect, it } from 'vitest'

import {
  editorMarkdownToStorageMarkdown,
  normalizeStorageMarkdown,
  storageMarkdownToEditorMarkdown,
} from '../extensions/markdownIO'

const roundTripCases = [
  ['plain text', '函数与导数'],
  ['inline math', '设 \\(x^2+1\\) 为函数。'],
  ['two inline formulas', '若 \\(a>0\\)，则 \\(b<0\\)。'],
  ['escaped backslash', '路径 C:\\\\temp 不应变化'],
  ['bold with inline math', '**结论**：\\(E=mc^2\\)。'],
  ['code span dollar', '输入 `npm $HOME` 不应变成公式。'],
  ['code fence dollar', '```ts\nconst price = "$100"\n```'],
  ['display math block', '$$\n\\int_0^1 x dx\n$$'],
  ['display math compact', '$$\\sum_{i=1}^n i$$'],
  ['mixed inline and block', '先看 \\(x\\)。\n\n$$\ny=x^2\n$$\n\n结束。'],
  ['escaped parentheses', '文本 \\(not math\\) 保持。'],
  ['empty inline ignored', '空公式 \\(   \\) 保留文本。'],
  ['cjk around math', '由\\(a+b\\)可得结果'],
  ['punctuation around math', '令（\\(x\\)）成立。'],
  ['matrix block', '$$\n\\begin{matrix}1&2\\\\3&4\\end{matrix}\n$$'],
  ['multiple paragraphs', '第一段 \\(a\\)。\n\n第二段 \\(b\\)。'],
  ['dollar currency text', '价格是 $100，不是公式。'],
  ['single dollar existing text', '旧文本 $x$ 会规范为行内公式。'],
  ['link with math text', '[查看 \\(x\\)](https://example.com)'],
  ['list with math', '- 条件 \\(a\\)\n- 结论 \\(b\\)'],
] as const

describe('RichTextarea markdown IO', () => {
  it.each(roundTripCases)('round-trips %s', (_name, markdown) => {
    const editorMarkdown = storageMarkdownToEditorMarkdown(markdown)
    const storageMarkdown = editorMarkdownToStorageMarkdown(editorMarkdown)

    expect(storageMarkdown).toBe(normalizeStorageMarkdown(markdown))
  })

  it('converts storage inline math to Tiptap mathematics markdown', () => {
    expect(storageMarkdownToEditorMarkdown('设 \\(x^2\\) 成立')).toBe('设 $x^2$ 成立')
  })

  it('converts Tiptap mathematics markdown back to storage inline math', () => {
    expect(editorMarkdownToStorageMarkdown('设 $x^2$ 成立')).toBe('设 \\(x^2\\) 成立')
  })
})
