import type { DeepThinkMetrics, DeepThinkStatus, ThinkingNode } from '@/hooks/useDeepThink'

export function getStatusLabel(status: DeepThinkStatus): string {
  if (status === 'idle') return '等待输入'
  if (status === 'searching') return '思维树搜索中'
  if (status === 'answering') return '生成最终解答中'
  if (status === 'done') return '已完成'
  return '出错'
}

export function getAssistantIndicatorTone(status: DeepThinkStatus): string {
  if (status === 'error') return 'bg-destructive'
  if (status === 'done') return 'bg-emerald-500'
  if (status === 'searching' || status === 'answering') return 'bg-primary'
  return 'bg-muted-foreground'
}

export function buildDeepStats(
  metrics: DeepThinkMetrics,
  nodes: Record<string, ThinkingNode>,
  subject: string,
  statusLabel: string
): Array<{ label: string; value: string }> {
  const nodeCountSummary = metrics.totalNodes || Object.keys(nodes).length
  return [
    { label: '状态', value: statusLabel },
    { label: '节点', value: `${nodeCountSummary}` },
    { label: '深度', value: `${metrics.currentDepth || 0}` },
    { label: '学科', value: subject || '待选择' },
  ]
}

export function buildConfigSummary(config: Record<string, unknown> | null): {
  bf: number
  bw: number
  md: number
  th: number
} | null {
  if (!config) return null
  const readNumber = (obj: Record<string, unknown>, key: string): number => {
    const v = obj[key]
    return typeof v === 'number' ? v : 0
  }
  return {
    bf: readNumber(config, 'branch_factor'),
    bw: readNumber(config, 'beam_width'),
    md: readNumber(config, 'max_depth'),
    th: readNumber(config, 'prune_threshold'),
  }
}
