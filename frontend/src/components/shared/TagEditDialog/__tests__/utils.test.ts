import { describe, expect, it } from 'vitest'
import { parseTagsInput } from '@/components/shared/TagEditDialog/utils'

describe('parseTagsInput', () => {
  it('deduplicates before enforcing the 20 tag limit', () => {
    const raw = ['重复', '重复', ...Array.from({ length: 21 }, (_, index) => `标签${index + 1}`)].join(',')

    const tags = parseTagsInput(raw)

    expect(tags).toHaveLength(20)
    expect(tags).toContain('标签19')
    expect(tags).not.toContain('标签20')
    expect(tags.filter((tag) => tag === '重复')).toHaveLength(1)
  })
})
