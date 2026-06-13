import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const tokensPath = resolve(process.cwd(), 'src/styles/tokens.css')
const tokensCss = readFileSync(tokensPath, 'utf8')

const REQUIRED_PRESET_PALETTE_TOKENS = [
  '--design-style-background',
  '--design-style-surface-100',
  '--design-style-surface-200',
  '--design-style-surface-300',
  '--design-style-surface-400',
  '--design-style-foreground',
  '--design-style-secondary',
  '--design-style-muted',
  '--design-style-accent',
  '--design-style-accent-hover',
  '--design-style-accent-active',
  '--design-style-on-accent',
  '--design-style-background-hsl',
  '--design-style-foreground-hsl',
  '--design-style-card-hsl',
  '--design-style-primary-hsl',
  '--design-style-muted-hsl',
  '--design-style-border-hsl',
]

const REQUIRED_RUNTIME_TOKENS = [
  '--color-env-void',
  '--surface-100',
  '--surface-200',
  '--surface-300',
  '--border-default-color',
  '--text-primary',
  '--text-secondary',
  '--accent-brand-base',
  '--accent-brand-hover',
  '--accent-brand-active',
  '--background',
  '--foreground',
  '--card',
  '--primary',
  '--primary-foreground',
  '--muted',
  '--muted-foreground',
  '--accent',
  '--border',
]

function extractDesignStyleBlock(value: string) {
  const match = tokensCss.match(new RegExp(`:root\\[data-design-style="${value}"\\]\\s*\\{([^}]*)\\}`))
  return match?.[1] ?? ''
}

function extractRuntimeMapperBlock() {
  const match = tokensCss.match(/:root\[data-design-style\]\s*\{([^}]*)\}/)
  return match?.[1] ?? ''
}

describe('design style presets', () => {
  it('defines a palette for every preview preset', async () => {
    vi.stubGlobal('matchMedia', () => ({ matches: false }))
    const { DESIGN_STYLE_PRESETS } = await import('@/stores/useAppearanceStore')

    for (const preset of DESIGN_STYLE_PRESETS) {
      const block = extractDesignStyleBlock(preset.value)

      expect(block, `${preset.value} is missing a data-design-style block`).not.toBe('')
      for (const token of REQUIRED_PRESET_PALETTE_TOKENS) {
        expect(block, `${preset.value} must define ${token}`).toContain(token)
      }
    }
  })

  it('maps preset palettes to the runtime tokens used by app chrome', () => {
    const block = extractRuntimeMapperBlock()

    expect(block, 'data-design-style runtime mapper is missing').not.toBe('')
    for (const token of REQUIRED_RUNTIME_TOKENS) {
      expect(block, `runtime mapper must define ${token}`).toContain(token)
    }
  })
})
