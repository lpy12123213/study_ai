import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const apiRoot = resolve(__dirname, '..')

function readApiFile(...parts: string[]) {
  return readFileSync(resolve(apiRoot, ...parts), 'utf-8')
}

describe('api module split boundaries', () => {
  it('keeps chat types and stream helpers out of the client barrel implementation', () => {
    const types = readApiFile('chat', 'types.ts')
    const sse = readApiFile('chat', 'sse.ts')

    expect(types).toContain('export interface SendMessageRequest')
    expect(types).not.toContain("from './client'")
    expect(sse).toContain('export function normalizeChatStreamEvent')
    expect(sse).not.toContain("from './client'")
  })

  it('keeps question-library types and stream helpers in dedicated files', () => {
    const types = readApiFile('questionLibrary', 'types.ts')
    const sse = readApiFile('questionLibrary', 'sse.ts')

    expect(types).toContain('export interface QuestionLibraryListItem')
    expect(types).not.toContain("from './client'")
    expect(sse).toContain('export function streamQuestionLibraryTask')
    expect(sse).not.toContain("from './client'")
  })

  it('keeps split modules available through api barrels', () => {
    const chatEntry = readApiFile('chat.ts')
    const chatBarrel = readApiFile('chat', 'index.ts')
    const questionLibraryEntry = readApiFile('questionLibrary.ts')
    const questionLibraryBarrel = readApiFile('questionLibrary', 'index.ts')

    expect(chatEntry).toContain("export * from './chat/types'")
    expect(chatEntry).toContain("export * from './chat/sse'")
    expect(chatEntry).toContain("export * from './chat/client'")
    expect(chatBarrel).toContain("export * from './types'")
    expect(chatBarrel).toContain("export * from './sse'")
    expect(chatBarrel).toContain("export * from './client'")
    expect(questionLibraryEntry).toContain("export * from './questionLibrary/types'")
    expect(questionLibraryEntry).toContain("export * from './questionLibrary/sse'")
    expect(questionLibraryEntry).toContain("export * from './questionLibrary/client'")
    expect(questionLibraryBarrel).toContain("export * from './types'")
    expect(questionLibraryBarrel).toContain("export * from './sse'")
    expect(questionLibraryBarrel).toContain("export * from './client'")
  })
})
