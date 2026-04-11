import type { AiGenerateKnowledgeNode } from '@/features/aiGenerate/types'

export function clampCount(raw: string): number {
  const value = Number(raw)
  if (!Number.isFinite(value)) return 5
  return Math.max(1, Math.min(10, Math.floor(value)))
}

export function statusLabel(status: string): string {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'pending_review') return '待审核'
  if (normalized === 'partial_failure') return '部分完成'
  if (normalized === 'archived_discarded') return '已归档'
  if (normalized === 'committed') return '已入库'
  if (normalized === 'stopped') return '已停止'
  if (normalized === 'running') return '运行中'
  if (normalized === 'failed') return '失败'
  if (normalized === 'archived') return '已归档'
  return normalized || '未开始'
}

export function historySort<T extends { updated_at_s?: number; created_at_s?: number }>(items: T[]): T[] {
  return [...items].sort((a, b) => Number(b.updated_at_s || b.created_at_s || 0) - Number(a.updated_at_s || a.created_at_s || 0))
}

export function flattenKnowledgeNodes(nodes: AiGenerateKnowledgeNode[]): Record<string, AiGenerateKnowledgeNode> {
  const out: Record<string, AiGenerateKnowledgeNode> = {}
  const visit = (node: AiGenerateKnowledgeNode) => {
    out[node.id] = node
    ;(node.children || []).forEach(visit)
  }
  nodes.forEach(visit)
  return out
}

