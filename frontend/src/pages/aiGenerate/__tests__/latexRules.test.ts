import { describe, expect, it } from 'vitest'
import { appendLatexConstraint } from '@/pages/aiGenerate/latexRules'

describe('appendLatexConstraint', () => {
  it('appends a strict latex rule to the mission payload', () => {
    const nextMission = appendLatexConstraint('为高一数学生成 3 道导数应用题。')

    expect(nextMission).toContain('所有数学公式必须使用 LaTeX')
    expect(nextMission).toContain('\\(...\\)')
    expect(nextMission).toContain('\\[...\\]')
  })
})
