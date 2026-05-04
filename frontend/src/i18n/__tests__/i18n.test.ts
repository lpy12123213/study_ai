import { describe, expect, it } from 'vitest'

import { createTranslator, normalizeLocale, resolveLocalePreference } from '@/i18n'

describe('i18n helpers', () => {
  it('normalizes supported locale aliases', () => {
    expect(normalizeLocale('zh')).toBe('zh-CN')
    expect(normalizeLocale('zh_CN')).toBe('zh-CN')
    expect(normalizeLocale('en')).toBe('en-US')
    expect(normalizeLocale('en-GB')).toBe('en-US')
    expect(normalizeLocale('fr-FR')).toBe('')
  })

  it('resolves explicit locale preferences before ambient settings', () => {
    expect(resolveLocalePreference('en-US')).toBe('en-US')
    expect(resolveLocalePreference('zh-CN')).toBe('zh-CN')
  })

  it('translates route and interpolated messages', () => {
    const t = createTranslator('en-US')

    expect(t('route.tasks')).toBe('Task Center')
    expect(t('history.openTask', { title: 'Draft' })).toBe('Open task: Draft')
    expect(t('missing.key')).toBe('missing.key')
  })
})
