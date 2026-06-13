import { matchPath } from 'react-router-dom'

import {
  Award,
  BarChart3,
  BookOpen,
  BookX,
  Brain,
  Bug,
  ClipboardCheck,
  Files,
  Film,
  LayoutTemplate,
  Library,
  ListChecks,
  ListTodo,
  MessagesSquare,
  PenTool,
  PenSquare,
  Search,
  Settings,
  Sparkles,
  Tag,
  TrendingUp,
  type LucideIcon,
} from 'lucide-react'

export type RouteLayout = 'fullscreen' | 'studio' | 'wide' | 'standard'
export type RouteNavGroup = 'main' | 'secondary' | 'hidden'

export type RouteConfig = {
  id: string
  path: string
  label: string
  title: string
  crumb: string
  icon: LucideIcon
  layout: RouteLayout
  sidebar: boolean
  navGroup: RouteNavGroup
  requireAuth: boolean
  command: boolean
  parentId?: string
}

type RouteConfigDefinition = Omit<RouteConfig, 'crumb' | 'requireAuth' | 'title'> & {
  crumb?: string
  requireAuth?: boolean
  title?: string
}

function defineRoute(config: RouteConfigDefinition): RouteConfig {
  return {
    crumb: config.label,
    requireAuth: true,
    title: config.label,
    ...config,
  }
}

export const ROUTE_CONFIG: RouteConfig[] = [
  defineRoute({ id: 'chat', path: '/chat', label: '对话', icon: MessagesSquare, layout: 'standard', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'chat-detail', path: '/chat/:conversationId', label: '会话详情', icon: MessagesSquare, layout: 'standard', sidebar: true, navGroup: 'hidden', command: false, parentId: 'chat' }),
  defineRoute({ id: 'deepthink', path: '/deepthink', label: '深度解题', icon: Brain, layout: 'wide', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'blueprint', path: '/blueprint', label: '蓝图组卷', icon: LayoutTemplate, layout: 'wide', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'study-materials', path: '/study-materials', label: '自学资料', icon: BookOpen, layout: 'wide', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'knowledge-videos', path: '/knowledge-videos', label: '知识视频', icon: Film, layout: 'wide', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'question-evaluate', path: '/question-evaluate', label: '好题鉴别', icon: Award, layout: 'wide', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'essay-evaluation', path: '/essay-evaluation', label: '作文批改', icon: PenSquare, layout: 'wide', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'question-library', path: '/question-library', label: '本地题库', icon: Library, layout: 'studio', sidebar: false, navGroup: 'main', command: true }),
  defineRoute({ id: 'ai-generate', path: '/ai-generate', label: 'AI 出题', icon: Sparkles, layout: 'studio', sidebar: false, navGroup: 'main', command: true }),
  defineRoute({ id: 'ai-generate-review', path: '/ai-generate/review/:sessionId/:questionId', label: '题目审核', icon: Sparkles, layout: 'studio', sidebar: false, navGroup: 'hidden', command: false, parentId: 'ai-generate' }),
  defineRoute({ id: 'papers', path: '/papers', label: '试卷管理', icon: Files, layout: 'standard', sidebar: true, navGroup: 'main', command: true }),
  defineRoute({ id: 'paper-detail', path: '/papers/:paperId', label: '试卷详情', icon: Files, layout: 'standard', sidebar: true, navGroup: 'hidden', command: false, parentId: 'papers' }),
  defineRoute({ id: 'exam-session', path: '/exam/:sessionId', label: '在线答题', icon: ClipboardCheck, layout: 'fullscreen', sidebar: false, navGroup: 'hidden', command: false }),
  defineRoute({ id: 'exam-result', path: '/exam/:sessionId/result', label: '考试成绩', icon: ClipboardCheck, layout: 'standard', sidebar: true, navGroup: 'hidden', command: false, parentId: 'papers' }),
  defineRoute({ id: 'canvas', path: '/canvas', label: '学习画布', icon: PenTool, layout: 'fullscreen', sidebar: false, navGroup: 'main', command: true }),
  defineRoute({ id: 'canvas-detail', path: '/canvas/:boardId', label: '学习画布', icon: PenTool, layout: 'fullscreen', sidebar: false, navGroup: 'hidden', command: false, parentId: 'canvas' }),
  defineRoute({ id: 'lesson-plans', path: '/lesson-plans', label: '教案生成', icon: BookOpen, layout: 'wide', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'lesson-plan-detail', path: '/lesson-plans/:lessonPlanId', label: '教案详情', icon: BookOpen, layout: 'wide', sidebar: true, navGroup: 'hidden', command: false, parentId: 'lesson-plans' }),
  defineRoute({ id: 'search', path: '/search', label: '全文搜索', icon: Search, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'tasks', path: '/tasks', label: '任务中心', icon: ListChecks, layout: 'wide', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'study-archives', path: '/study-archives', label: '学习档案', icon: BookOpen, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'study-archive-detail', path: '/study-archives/:archiveId', label: '学习档案详情', icon: BookOpen, layout: 'standard', sidebar: true, navGroup: 'hidden', command: false, parentId: 'study-archives' }),
  defineRoute({ id: 'exports', path: '/exports', label: '导出中心', icon: Files, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'templates', path: '/templates', label: '模板库', icon: LayoutTemplate, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'learning-plans', path: '/learning-plans', label: '学习计划', icon: ListTodo, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'wrongbook', path: '/wrongbook', label: '错题本', icon: BookX, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'annotations', path: '/annotations', label: '批注', icon: Tag, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'feedback', path: '/feedback', label: '反馈', icon: Bug, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'dashboard', path: '/dashboard', label: '仪表盘', icon: BarChart3, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'insights', path: '/insights', label: '学情分析', icon: TrendingUp, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'diff', path: '/diff', label: '内容对比', icon: Files, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'settings', path: '/settings', label: '设置', icon: Settings, layout: 'standard', sidebar: true, navGroup: 'secondary', command: true }),
  defineRoute({ id: 'dev-rich-textarea', path: '/dev/rich-textarea', label: 'RichTextarea', icon: Bug, layout: 'wide', sidebar: false, navGroup: 'hidden', command: false, requireAuth: false }),
]

export const HEADER_NAV_ITEMS = ROUTE_CONFIG.filter((route) => route.navGroup === 'main')
export const COMMAND_ROUTE_ITEMS = ROUTE_CONFIG.filter((route) => route.command)

export type RouteCrumb = {
  id: string
  label: string
  path: string
  current: boolean
}

function matchRoutePath(pathname: string, routePath: string): boolean {
  if (routePath.includes(':')) {
    return Boolean(matchPath({ path: routePath, end: false }, pathname))
  }
  return pathname === routePath || pathname.startsWith(`${routePath}/`)
}

export function isRouteActive(pathname: string, routePath: string): boolean {
  return matchRoutePath(pathname, routePath)
}

export function matchRouteConfig(pathname: string): RouteConfig {
  const normalized = pathname || '/'
  const sorted = [...ROUTE_CONFIG].sort((a, b) => b.path.length - a.path.length)
  return sorted.find((route) => matchRoutePath(normalized, route.path)) || ROUTE_CONFIG[0]
}

export function getRouteConfig(path: string): RouteConfig | undefined {
  return ROUTE_CONFIG.find((route) => route.path === path)
}

export function getRouteConfigById(id: string): RouteConfig | undefined {
  return ROUTE_CONFIG.find((route) => route.id === id)
}

export function getRouteConfigFromMatches(matches: Array<{ handle?: unknown }>): RouteConfig | undefined {
  for (const match of [...matches].reverse()) {
    const handle = match.handle as { routeConfig?: RouteConfig } | undefined
    if (handle?.routeConfig) return handle.routeConfig
  }
  return undefined
}

export function getRouteCrumbs(pathname: string, route: RouteConfig = matchRouteConfig(pathname)): RouteCrumb[] {
  const chain: RouteConfig[] = []
  let cursor: RouteConfig | undefined = route

  while (cursor) {
    chain.unshift(cursor)
    cursor = cursor.parentId ? getRouteConfigById(cursor.parentId) : undefined
  }

  return chain.map((item, index) => {
    const current = index === chain.length - 1
    return {
      id: item.id,
      label: item.crumb,
      path: item.path.includes(':') ? pathname : item.path,
      current,
    }
  })
}
