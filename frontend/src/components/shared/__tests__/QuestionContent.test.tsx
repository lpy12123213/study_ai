import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionContent } from '@/components/shared/QuestionContent'

const clientMocks = vi.hoisted(() => ({
  downloadObjectUrl: vi.fn(),
  resolveApiResourceUrl: vi.fn((url: string) => `https://example.test${url.startsWith('/') ? url : `/${url}`}`),
}))

vi.mock('@/api/client', () => ({
  downloadObjectUrl: clientMocks.downloadObjectUrl,
  resolveApiResourceUrl: clientMocks.resolveApiResourceUrl,
}))

describe('QuestionContent', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    clientMocks.downloadObjectUrl.mockResolvedValue({
      objectUrl: 'blob:question-content-image',
      revoke: vi.fn(),
    })
  })

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

  it('loads generated media image tokens through authenticated blob URLs', async () => {
    const imageUrl = `/api/media/generated/${'c'.repeat(64)}.png`
    render(<QuestionContent content={`如图所示：[图片:${imageUrl}]`} />)

    const image = await screen.findByAltText('题目图片')
    await waitFor(() => expect(image).toHaveAttribute('src', 'blob:question-content-image'))
    expect(clientMocks.downloadObjectUrl).toHaveBeenCalledWith(imageUrl)
  })

  it('loads proxied question media through authenticated blob URLs', async () => {
    const imageUrl = '/api/media/proxy?url=https%3A%2F%2Fzujuan.xkw.com%2Fstatic%2Fquestion.png'
    render(<QuestionContent content={`如图所示：[图片:${imageUrl}]`} />)

    const image = await screen.findByAltText('题目图片')
    await waitFor(() => expect(image).toHaveAttribute('src', 'blob:question-content-image'))
    expect(clientMocks.downloadObjectUrl).toHaveBeenCalledWith(imageUrl)
  })

  it('renders crawled formula hash placeholders as formula images', () => {
    const hash = '294f5ba74cdf695fc9a8a8e52f421328'
    render(<QuestionContent content={`已知速度为[公式:${hash}]，求位移。`} />)

    const formula = screen.getByAltText('题目公式')
    expect(formula).toHaveAttribute('src', expect.stringContaining(`${hash}.svg`))
  })
})
