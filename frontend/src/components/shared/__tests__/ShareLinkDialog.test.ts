import { describe, expect, it } from 'vitest'
import { secondsForPreset } from '@/components/shared/ShareLinkDialog'

describe('ShareLinkDialog', () => {
  it('maps the never preset to the backend no-expiration value', () => {
    expect(secondsForPreset('never')).toBe(0)
  })
})
