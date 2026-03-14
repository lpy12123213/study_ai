import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { QuestionContent } from '@/components/shared/QuestionContent'

describe('QuestionContent', () => {
  it('renders $...$ and $$...$$ formulas via KaTeX', () => {
    const { container } = render(
      <QuestionContent content={'行内 $x^2+1$，块 $$\\frac{1}{2}$$。'} />
    )

    expect(container.querySelector('.katex')).not.toBeNull()
    expect(container.querySelector('.katex-display')).not.toBeNull()
  })

  it('rescues obvious broken probability tables into display math', () => {
    const content = `已知随机变量的取值为非负整数，其分布列为：

ξ
0
1
2
...
n

P
p_0
p_1
p_2
...
p_n`

    const { container } = render(<QuestionContent content={content} />)

    expect(container.querySelector('.katex-display')).not.toBeNull()
    expect(container.textContent || '').toContain('已知随机变量的取值为非负整数')
  })

  it('rescues obvious broken generic frequency tables into display math', () => {
    const content = `出拳情况
石头
剪刀
布

甲
30次
20次
10次

乙
15次
30次
15次`

    const { container } = render(<QuestionContent content={content} />)

    expect(container.querySelector('.katex-display')).not.toBeNull()
    expect(container.textContent || '').toContain('出拳情况')
    expect(container.textContent || '').toContain('石头')
    expect(container.textContent || '').toContain('30次')
  })

  it('rescues broken tables when the header starts at the tail of a paragraph', () => {
    const content = `甲乙二人的最近60次出拳如下表．
出拳情况
石头
剪刀
布

甲
30次
20次
10次

乙
15次
30次
15次

用频率估计概率，假设两人每次出拳相互独立．`

    const { container } = render(<QuestionContent content={content} />)

    expect(container.querySelector('.katex-display')).not.toBeNull()
    expect(container.textContent || '').toContain('甲乙二人的最近60次出拳如下表')
    expect(container.textContent || '').toContain('出拳情况')
    expect(container.textContent || '').toContain('用频率估计概率')
  })
})
