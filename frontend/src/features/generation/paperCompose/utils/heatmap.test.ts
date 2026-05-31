import { describe, it, expect } from 'vitest'

import type { Question } from '@/types'

import { bucketDifficulty, buildHeatmap, questionKnowledgePoints } from './heatmap'

describe('bucketDifficulty', () => {
  it('prefers numeric difficulty_value: smaller is harder', () => {
    expect(bucketDifficulty({ questionId: 'a', difficultyValue: 0.2 })).toBe('hard')
    expect(bucketDifficulty({ questionId: 'a', difficultyValue: 0.55 })).toBe('medium')
    expect(bucketDifficulty({ questionId: 'a', difficultyValue: 0.85 })).toBe('easy')
  })

  it('falls back to Chinese difficulty text', () => {
    expect(bucketDifficulty({ questionId: 'a', difficulty: '困难' })).toBe('hard')
    expect(bucketDifficulty({ questionId: 'a', difficulty: '中等' })).toBe('medium')
    expect(bucketDifficulty({ questionId: 'a', difficulty: '简单' })).toBe('easy')
    expect(bucketDifficulty({ questionId: 'a', difficulty: '' })).toBe('unknown')
  })
})

describe('questionKnowledgePoints', () => {
  it('prefers array over single field', () => {
    expect(
      questionKnowledgePoints({
        questionId: 'a',
        knowledgePoint: '函数',
        knowledgePoints: ['导数', '极值'],
      })
    ).toEqual(['导数', '极值'])
  })

  it('falls back to single knowledgePoint string', () => {
    expect(questionKnowledgePoints({ questionId: 'a', knowledgePoint: '函数' })).toEqual(['函数'])
  })
})

describe('buildHeatmap', () => {
  it('aggregates counts by kp x difficulty and tracks max cell count', () => {
    const qs: Question[] = [
      { questionId: '1', knowledgePoint: '函数', difficulty: '简单' },
      { questionId: '2', knowledgePoint: '函数', difficulty: '简单' },
      { questionId: '3', knowledgePoint: '函数', difficulty: '中等' },
      { questionId: '4', knowledgePoint: '几何', difficulty: '困难' },
    ]
    const heat = buildHeatmap(qs)
    expect(heat.knowledgePoints).toEqual(['函数', '几何'])
    expect(heat.totalQuestions).toBe(4)
    expect(heat.maxCellCount).toBe(2)
    const fnEasy = heat.cells.find((c) => c.knowledgePoint === '函数' && c.bucket === 'easy')
    expect(fnEasy?.count).toBe(2)
    expect(fnEasy?.questionIds).toEqual(['1', '2'])
  })

  it('counts uncategorized questions separately', () => {
    const qs: Question[] = [
      { questionId: '1', knowledgePoint: '函数' },
      { questionId: '2' },
      { questionId: '3' },
    ]
    const heat = buildHeatmap(qs)
    expect(heat.uncategorizedCount).toBe(2)
    expect(heat.totalQuestions).toBe(3)
  })

  it('caps knowledge points to top-N by count', () => {
    const qs: Question[] = [
      { questionId: '1', knowledgePoint: 'A' },
      { questionId: '2', knowledgePoint: 'A' },
      { questionId: '3', knowledgePoint: 'B' },
      { questionId: '4', knowledgePoint: 'C' },
    ]
    const heat = buildHeatmap(qs, { maxKnowledgePoints: 2 })
    expect(heat.knowledgePoints).toEqual(['A', 'B'])
    // 'C' should NOT contribute to cells
    expect(heat.cells.every((c) => c.knowledgePoint !== 'C')).toBe(true)
  })
})
