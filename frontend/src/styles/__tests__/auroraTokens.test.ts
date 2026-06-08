import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const tokensCss = readFileSync(resolve(process.cwd(), 'src/styles/tokens.css'), 'utf8')

describe('Aurora design tokens', () => {
  it('defines the core Aurora token contract', () => {
    const requiredTokens = [
      '--color-env-void',
      '--color-env-glow-primary',
      '--color-env-glow-ai',
      '--surface-100',
      '--surface-200',
      '--surface-300',
      '--surface-400',
      '--border-subtle',
      '--border-default',
      '--border-strong',
      '--border-glow-primary',
      '--text-display',
      '--text-primary',
      '--text-secondary',
      '--text-tertiary',
      '--text-inverse',
      '--accent-brand-base',
      '--accent-brand-hover',
      '--accent-brand-active',
      '--accent-ai-base',
      '--accent-ai-gradient',
      '--space-0-5',
      '--space-16',
      '--radius-pill',
      '--shadow-glow-sm',
      '--shadow-glow-md',
      '--shadow-glow-lg',
      '--shadow-elevation-high',
      '--z-toast',
      '--dur-fast',
      '--dur-base',
      '--dur-slow',
      '--ease-emphasized',
      '--spring-snappy',
      '--spring-smooth',
      '--spring-gentle',
    ]

    for (const token of requiredTokens) {
      expect(tokensCss, `${token} is missing`).toContain(token)
    }
  })

  it('ships reusable core scene classes without blob or orb decorations', () => {
    const requiredClasses = [
      '.aurora-app-shell',
      '.aurora-layout-surface',
      '.aurora-chat-user',
      '.aurora-chat-assistant',
      '.aurora-tool-card',
      '.aurora-tool-card[data-state="executing"]',
      '.aurora-exam-canvas',
      '.aurora-exam-card',
      '.aurora-exam-card[data-focus="true"]',
    ]

    for (const className of requiredClasses) {
      expect(tokensCss, `${className} is missing`).toContain(className)
    }

    expect(tokensCss).not.toMatch(/aurora-(blob|orb)/i)
  })
})
