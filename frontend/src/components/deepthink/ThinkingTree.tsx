import { useMemo } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import type { ThinkingNode } from '@/hooks/useDeepThink'

const NODE_W = 280
const NODE_H = 112
const COL_GAP = 120
const ROW_GAP = 24
const PAD = 24

function scoreTone(score: number | null): string {
  if (score == null) return 'bg-muted text-muted-foreground'
  if (score >= 7) return 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
  if (score >= 4) return 'bg-amber-500/15 text-amber-700 dark:text-amber-400'
  return 'bg-rose-500/15 text-rose-600 dark:text-rose-400'
}

function statusTone(status: string): string {
  if (status === 'selected') return 'border-primary/60 shadow-[0_0_0_1px_rgba(99,102,241,0.25)]'
  if (status === 'final') return 'border-primary shadow-[0_0_0_1px_rgba(99,102,241,0.35)]'
  if (status === 'pruned') return 'border-border/40 opacity-50'
  if (status === 'pending') return 'border-primary/30'
  return 'border-border'
}

export function ThinkingTree({
  nodes,
  bestPath,
  selectedNodeId,
  onSelectNode,
}: {
  nodes: Record<string, ThinkingNode>
  bestPath: string[]
  selectedNodeId?: string | null
  onSelectNode?: (nodeId: string) => void
}) {
  const { nodeList, bestSet, positions, edges, canvasW, canvasH, useAnimations } = useMemo(() => {
    const nodeList = Object.values(nodes)
    const bestSet = new Set(bestPath || [])
    const useAnimations = nodeList.length <= 300

    // Group nodes by depth; stable order via `createdAt`.
    const byDepth = new Map<number, ThinkingNode[]>()
    for (const n of nodeList) {
      const depth = typeof n.depth === 'number' ? n.depth : 0
      const arr = byDepth.get(depth) || []
      arr.push(n)
      byDepth.set(depth, arr)
    }
    for (const [depth, arr] of byDepth.entries()) {
      arr.sort((a, b) => (a.createdAt ?? 0) - (b.createdAt ?? 0) || a.id.localeCompare(b.id))
      byDepth.set(depth, arr)
    }

    const maxDepth = Math.max(0, ...Array.from(byDepth.keys()))
    const maxRows = Math.max(1, ...Array.from(byDepth.values()).map((arr) => arr.length))
    const canvasW = PAD * 2 + (maxDepth + 1) * NODE_W + maxDepth * COL_GAP
    const canvasH = PAD * 2 + maxRows * NODE_H + Math.max(0, maxRows - 1) * ROW_GAP

    const positions: Record<string, { x: number; y: number }> = {}
    for (const [depth, arr] of byDepth.entries()) {
      for (let i = 0; i < arr.length; i++) {
        const n = arr[i]
        positions[n.id] = {
          x: PAD + depth * (NODE_W + COL_GAP),
          y: PAD + i * (NODE_H + ROW_GAP),
        }
      }
    }

    const edges = nodeList
      .filter((n) => n.parentId)
      .map((n) => {
        const p = n.parentId ? positions[n.parentId] : null
        const c = positions[n.id]
        if (!p || !c) return null

        const startX = p.x + NODE_W
        const startY = p.y + NODE_H / 2
        const endX = c.x
        const endY = c.y + NODE_H / 2
        const c1x = startX + COL_GAP / 2
        const c2x = endX - COL_GAP / 2
        const d = `M ${startX} ${startY} C ${c1x} ${startY}, ${c2x} ${endY}, ${endX} ${endY}`

        const isBest = bestSet.has(n.id) && n.parentId && bestSet.has(n.parentId)
        const isPruned = n.status === 'pruned'

        return { id: `${n.parentId}__${n.id}`, d, isBest, isPruned }
      })
      .filter(Boolean) as Array<{ id: string; d: string; isBest: boolean; isPruned: boolean }>

    return { nodeList, bestSet, positions, edges, canvasW, canvasH, useAnimations }
  }, [nodes, bestPath])

  return (
    <div className="relative w-full h-full overflow-auto rounded-xl border border-border bg-card">
      <div className="relative" style={{ width: canvasW, height: canvasH }}>
        <svg className="absolute inset-0" width={canvasW} height={canvasH}>
          {edges.map((e) => (
            <path
              key={e.id}
              d={e.d}
              fill="none"
              strokeWidth={2}
              strokeDasharray={e.isPruned ? '6 6' : undefined}
              className={cn(
                e.isBest
                  ? 'stroke-primary/70'
                  : e.isPruned
                    ? 'stroke-muted-foreground/20'
                    : 'stroke-border',
              )}
            />
          ))}
        </svg>

        {useAnimations ? (
          <AnimatePresence>
            {nodeList.map((n) => {
              const pos = positions[n.id]
              if (!pos) return null
              const isSelected = selectedNodeId === n.id
              const isBest = bestSet.has(n.id)
              const scoreText =
                n.score == null ? '...' : Number.isFinite(n.score) ? n.score.toFixed(1) : String(n.score)

              return (
                <motion.button
                  key={n.id}
                  type="button"
                  initial={{ opacity: 0, scale: 0.98, y: 6 }}
                  animate={{ opacity: 1, scale: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.98 }}
                  transition={{ duration: 0.2 }}
                  onClick={() => onSelectNode?.(n.id)}
                  className={cn(
                    'absolute text-left rounded-xl border bg-background/60 backdrop-blur px-3 py-2 shadow-sm hover:bg-background transition-colors',
                    statusTone(n.status),
                    isBest && 'ring-2 ring-primary/20',
                    isSelected && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
                    n.status === 'pruned' && 'line-through',
                  )}
                  style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[11px] font-medium text-muted-foreground tabular-nums">D{n.depth}</div>
                    <div
                      className={cn(
                        'text-[11px] font-medium tabular-nums px-2 py-0.5 rounded-md',
                        scoreTone(n.score),
                      )}
                      title={n.evalReasoning || ''}
                    >
                      {scoreText}
                    </div>
                  </div>

                  <div className="mt-2 text-sm font-medium leading-5 line-clamp-2">{n.thought}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">
                    {n.reasoning || '（无步骤说明）'}
                  </div>
                </motion.button>
              )
            })}
          </AnimatePresence>
        ) : (
          <>
            {nodeList.map((n) => {
              const pos = positions[n.id]
              if (!pos) return null
              const isSelected = selectedNodeId === n.id
              const isBest = bestSet.has(n.id)
              const scoreText =
                n.score == null ? '...' : Number.isFinite(n.score) ? n.score.toFixed(1) : String(n.score)

              return (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => onSelectNode?.(n.id)}
                  className={cn(
                    'absolute text-left rounded-xl border bg-background/60 backdrop-blur px-3 py-2 shadow-sm hover:bg-background transition-colors',
                    statusTone(n.status),
                    isBest && 'ring-2 ring-primary/20',
                    isSelected && 'ring-2 ring-primary ring-offset-2 ring-offset-background',
                    n.status === 'pruned' && 'line-through',
                  )}
                  style={{ left: pos.x, top: pos.y, width: NODE_W, height: NODE_H }}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="text-[11px] font-medium text-muted-foreground tabular-nums">D{n.depth}</div>
                    <div
                      className={cn(
                        'text-[11px] font-medium tabular-nums px-2 py-0.5 rounded-md',
                        scoreTone(n.score),
                      )}
                      title={n.evalReasoning || ''}
                    >
                      {scoreText}
                    </div>
                  </div>

                  <div className="mt-2 text-sm font-medium leading-5 line-clamp-2">{n.thought}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground line-clamp-2">
                    {n.reasoning || '（无步骤说明）'}
                  </div>
                </button>
              )
            })}
          </>
        )}
      </div>
    </div>
  )
}

