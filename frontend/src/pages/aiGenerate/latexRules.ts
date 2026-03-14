export const LATEX_RULE_TEXT = '所有数学公式强制使用 LaTeX，行内公式用 \\(...\\)，独立公式用 \\[...\\]。'

const LATEX_RULE_SUFFIX =
  '输出要求：所有数学公式必须使用 LaTeX；行内公式用 \\(...\\)，独立公式用 \\[...\\]；不要使用图片公式、MathML、SVG 或自然语言替代公式。'

export function appendLatexConstraint(missionText: string): string {
  const trimmed = String(missionText || '').trim()
  if (!trimmed) return ''
  if (trimmed.includes('LaTeX') && trimmed.includes('\\(...\\)') && trimmed.includes('\\[...\\]')) {
    return trimmed
  }
  return `${trimmed}\n\n${LATEX_RULE_SUFFIX}`
}
