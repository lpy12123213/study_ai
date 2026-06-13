import { describe, expect, it } from 'vitest'
import {
  getRouteConfigById,
  getRouteCrumbs,
  HEADER_NAV_ITEMS,
  matchRouteConfig,
} from '@/router/routes.config'

describe('routes.config', () => {
  it('keeps the main header nav derivation stable', () => {
    const ids = HEADER_NAV_ITEMS.map((route) => route.id)
    expect(ids).toEqual([
      'chat',
      'deepthink',
      'blueprint',
      'study-materials',
      'knowledge-videos',
      'question-evaluate',
      'essay-evaluation',
      'question-library',
      'ai-generate',
      'papers',
      'canvas',
    ])
  })

  it('matches the study-archives parent route', () => {
    expect(matchRouteConfig('/study-archives').id).toBe('study-archives')
    expect(matchRouteConfig('/study-archives/42').id).toBe('study-archive-detail')
  })

  it('builds two-level crumbs for detail routes', () => {
    const paperCrumbs = getRouteCrumbs('/papers/123')
    expect(paperCrumbs.map((c) => c.id)).toEqual(['papers', 'paper-detail'])
    expect(paperCrumbs[0].path).toBe('/papers')
    expect(paperCrumbs[1].current).toBe(true)

    const archiveCrumbs = getRouteCrumbs('/study-archives/42')
    expect(archiveCrumbs.map((c) => c.id)).toEqual(['study-archives', 'study-archive-detail'])
    expect(archiveCrumbs[0].path).toBe('/study-archives')
    expect(archiveCrumbs[1].path).toBe('/study-archives/42')
  })

  it('builds crumbs from an explicitly resolved route config', () => {
    const detail = getRouteConfigById('lesson-plan-detail')
    expect(detail).toBeDefined()
    const crumbs = getRouteCrumbs('/lesson-plans/7', detail)
    expect(crumbs.map((c) => c.id)).toEqual(['lesson-plans', 'lesson-plan-detail'])
  })
})
