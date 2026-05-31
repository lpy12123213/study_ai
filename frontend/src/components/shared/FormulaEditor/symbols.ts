import type { FormulaSubject } from './useFormulaEditor'

export type FormulaSymbol = {
  /** UI label rendered on the toolbar button. */
  label: string
  /** LaTeX snippet inserted into the editor when the button is clicked. */
  latex: string
  /** Optional accessibility description (defaults to ``label``). */
  description?: string
}

export type FormulaSymbolGroup = {
  id: string
  title: string
  /** Subjects this group applies to. ``'general'`` is always shown. */
  subjects: FormulaSubject[]
  symbols: FormulaSymbol[]
}

/**
 * Static catalogue of LaTeX snippets surfaced by {@link FormulaToolbar}.
 *
 * Splitting per subject keeps the math toolbar focused for math/语数 use cases
 * and lets physics/chemistry users get the relevant operators upfront. The
 * ``general`` group is always rendered so common Greek letters and brackets
 * are available regardless of subject.
 */
export const FORMULA_SYMBOL_GROUPS: FormulaSymbolGroup[] = [
  {
    id: 'general',
    title: '常用',
    subjects: ['general'],
    symbols: [
      { label: '+', latex: '+' },
      { label: '−', latex: '-' },
      { label: '×', latex: '\\times ' },
      { label: '÷', latex: '\\div ' },
      { label: '=', latex: '=' },
      { label: '≠', latex: '\\neq ' },
      { label: '≈', latex: '\\approx ' },
      { label: '<', latex: '<' },
      { label: '>', latex: '>' },
      { label: '≤', latex: '\\leq ' },
      { label: '≥', latex: '\\geq ' },
      { label: '±', latex: '\\pm ' },
      { label: '∞', latex: '\\infty ' },
      { label: '⋯', latex: '\\cdots ' },
    ],
  },
  {
    id: 'algebra',
    title: '代数',
    subjects: ['math'],
    symbols: [
      { label: 'a/b', latex: '\\frac{a}{b}', description: '分式 a/b' },
      { label: '√', latex: '\\sqrt{}', description: '平方根' },
      { label: 'ⁿ√', latex: '\\sqrt[n]{}', description: 'n 次根' },
      { label: 'aⁿ', latex: '^{n}', description: '指数' },
      { label: 'aₙ', latex: '_{n}', description: '下标' },
      { label: 'log', latex: '\\log_{}\\!{}', description: '对数' },
      { label: 'ln', latex: '\\ln ' },
      { label: 'lg', latex: '\\lg ' },
      { label: '|x|', latex: '\\left| x \\right|' },
    ],
  },
  {
    id: 'calculus',
    title: '微积分',
    subjects: ['math'],
    symbols: [
      { label: 'lim', latex: '\\lim_{x \\to }', description: '极限' },
      { label: '∑', latex: '\\sum_{i=1}^{n}' },
      { label: '∏', latex: '\\prod_{i=1}^{n}' },
      { label: '∫', latex: '\\int_{a}^{b}' },
      { label: '∮', latex: '\\oint' },
      { label: 'd/dx', latex: '\\frac{d}{dx}' },
      { label: '∂/∂x', latex: '\\frac{\\partial}{\\partial x}' },
      { label: "f'", latex: "f^{\\prime}" },
      { label: '∇', latex: '\\nabla ' },
    ],
  },
  {
    id: 'sets',
    title: '集合',
    subjects: ['math'],
    symbols: [
      { label: '∈', latex: '\\in ' },
      { label: '∉', latex: '\\notin ' },
      { label: '⊂', latex: '\\subset ' },
      { label: '⊆', latex: '\\subseteq ' },
      { label: '∪', latex: '\\cup ' },
      { label: '∩', latex: '\\cap ' },
      { label: '∅', latex: '\\varnothing ' },
      { label: 'ℝ', latex: '\\mathbb{R}' },
      { label: 'ℕ', latex: '\\mathbb{N}' },
      { label: 'ℤ', latex: '\\mathbb{Z}' },
      { label: 'ℚ', latex: '\\mathbb{Q}' },
    ],
  },
  {
    id: 'geometry',
    title: '几何',
    subjects: ['math'],
    symbols: [
      { label: '∠', latex: '\\angle ' },
      { label: '⊥', latex: '\\perp ' },
      { label: '∥', latex: '\\parallel ' },
      { label: '△', latex: '\\triangle ' },
      { label: '⊙', latex: '\\odot ' },
      { label: '°', latex: '^{\\circ}' },
      { label: 'sin', latex: '\\sin ' },
      { label: 'cos', latex: '\\cos ' },
      { label: 'tan', latex: '\\tan ' },
    ],
  },
  {
    id: 'matrix',
    title: '矩阵',
    subjects: ['math'],
    symbols: [
      {
        label: '矩阵',
        latex: '\\begin{pmatrix}a & b\\\\ c & d\\end{pmatrix}',
        description: '2×2 矩阵',
      },
      {
        label: '方程组',
        latex: '\\begin{cases}a\\\\ b\\end{cases}',
        description: 'cases 方程组',
      },
      {
        label: '行列式',
        latex: '\\begin{vmatrix}a & b\\\\ c & d\\end{vmatrix}',
        description: '行列式',
      },
    ],
  },
  {
    id: 'physics',
    title: '物理',
    subjects: ['physics'],
    symbols: [
      { label: '⃗v', latex: '\\vec{v}', description: '矢量' },
      { label: 'F', latex: '\\vec{F}' },
      { label: 'Δx', latex: '\\Delta x' },
      { label: 'm/s', latex: '\\,\\mathrm{m/s}' },
      { label: 'N', latex: '\\,\\mathrm{N}' },
      { label: 'J', latex: '\\,\\mathrm{J}' },
      { label: 'kg', latex: '\\,\\mathrm{kg}' },
      { label: 'A', latex: '\\,\\mathrm{A}' },
      { label: 'V', latex: '\\,\\mathrm{V}' },
      { label: 'Ω', latex: '\\,\\Omega ' },
    ],
  },
  {
    id: 'chemistry',
    title: '化学',
    subjects: ['chemistry'],
    symbols: [
      { label: '→', latex: ' \\rightarrow ' },
      { label: '⇌', latex: ' \\rightleftharpoons ' },
      { label: '↑', latex: ' \\uparrow ' },
      { label: '↓', latex: ' \\downarrow ' },
      { label: 'H₂O', latex: '\\mathrm{H_2O}' },
      { label: 'CO₂', latex: '\\mathrm{CO_2}' },
      { label: 'SO₄²⁻', latex: '\\mathrm{SO_4^{2-}}' },
      { label: 'Δ', latex: '\\overset{\\Delta}{\\rightarrow}' },
    ],
  },
  {
    id: 'greek',
    title: '希腊字母',
    subjects: ['general'],
    symbols: [
      { label: 'α', latex: '\\alpha ' },
      { label: 'β', latex: '\\beta ' },
      { label: 'γ', latex: '\\gamma ' },
      { label: 'δ', latex: '\\delta ' },
      { label: 'ε', latex: '\\varepsilon ' },
      { label: 'θ', latex: '\\theta ' },
      { label: 'λ', latex: '\\lambda ' },
      { label: 'μ', latex: '\\mu ' },
      { label: 'π', latex: '\\pi ' },
      { label: 'σ', latex: '\\sigma ' },
      { label: 'φ', latex: '\\varphi ' },
      { label: 'ω', latex: '\\omega ' },
      { label: 'Δ', latex: '\\Delta ' },
      { label: 'Ω', latex: '\\Omega ' },
    ],
  },
]

export function visibleGroupsForSubject(subject: FormulaSubject): FormulaSymbolGroup[] {
  return FORMULA_SYMBOL_GROUPS.filter(
    (g) => g.subjects.includes('general') || g.subjects.includes(subject),
  )
}
