import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ChevronDown, ChevronRight, Loader2, FileText, Search, Wrench } from 'lucide-react'
import { filterTaskTimelineNoise } from '@/components/task/TaskTimeline'
import {
  bundleConsecutiveToolRows,
  calcToolLogSummary,
  formatToolLogRow,
  type ToolLogBundledRow,
  type ToolLogRow,
} from '@/features/shared/toolUseLogFormat'
import { cn } from '@/lib/utils'
import type { TaskStep } from '@/types'

type ToolUseLogPanelProps = {
  steps: TaskStep[]
  disableMotion?: boolean
}

/** 格式化数字为固定宽度（2位） */
function fmtCount(n: number): string {
  return n.toString().padStart(2, '\u2007') // figure space for alignment
}

/** 单个工具行的悬停展示 */
function LogLineWithTooltip({
  row,
}: {
  row: ToolLogRow
}) {
  const iconMap = {
    read: FileText,
    search: Search,
    thought: Wrench,
    action: Wrench,
  }
  const Icon = iconMap[row.bucket] || Wrench

  const statusColor =
    row.status === 'running'
      ? 'text-blue-400'
      : row.status === 'failed'
        ? 'text-red-400'
        : 'text-zinc-400'

  return (
    <div className="group py-0.5">
      <div
        className={cn(
          'flex min-w-0 cursor-default items-center gap-2 rounded px-1.5 py-0.5 transition-colors',
          'group-hover:bg-zinc-800/60 group-hover:text-zinc-200'
        )}
      >
        <Icon className={cn('h-3 w-3 shrink-0', statusColor)} aria-hidden />
        <span className="w-20 shrink-0 font-medium text-zinc-300">{row.verb}</span>
        <span className="min-w-0 truncate text-zinc-500 group-hover:text-zinc-300">{row.detail}</span>
      </div>

      {row.detail && (
        <div className="ml-6 mt-1 hidden max-h-28 overflow-y-auto rounded-md border border-zinc-800 bg-zinc-900/95 px-2.5 py-2 text-[11px] leading-relaxed text-zinc-300 shadow-inner group-hover:block">
          <div className="font-medium text-zinc-200">{row.verb}</div>
          <div className="mt-1 break-words text-zinc-400">{row.detail}</div>
          {row.searchBrand && (
            <div className="mt-1 text-zinc-500">Provider: {row.searchBrand}</div>
          )}
        </div>
      )}
    </div>
  )
}

function NestedBundlePanel({
  pack,
  disableMotion,
}: {
  pack: ToolLogBundledRow
  disableMotion: boolean
}) {
  const [open, setOpen] = useState(false)
  const first = pack.rows[0]
  const count = pack.rows.length
  if (!first || count < 2) return null

  const runningHere = pack.rows.some((s) => s.status === 'running')

  // 计算该组内的读取/搜索/其他数量
  const reads = pack.rows.filter((r) => r.bucket === 'read').length
  const searches = pack.rows.filter((r) => r.bucket === 'search').length
  const others = pack.rows.filter((r) => r.bucket === 'thought' || r.bucket === 'action').length

  const list = (
    <div className="mt-1 space-y-0.5 border-l border-zinc-700/50 pl-2">
      {pack.rows.map((r) => (
        <LogLineWithTooltip key={r.id} row={r} />
      ))}
    </div>
  )

  const trigger = (
    <button
      type="button"
      aria-expanded={open}
      onClick={() => setOpen((v) => !v)}
      className={cn(
        'flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left transition-colors',
        'hover:bg-zinc-800/60 hover:text-zinc-200'
      )}
    >
      <span className="shrink-0 text-zinc-500">
        <ChevronRight className={cn('h-3 w-3 transition-transform', open && 'rotate-90')} aria-hidden />
      </span>
      {/* 等宽展示：读取 | 搜索 | 其他 */}
      <span className="flex items-center gap-2 font-mono text-[11px] tabular-nums">
        <span className={cn('inline-flex w-12 items-center gap-1', reads > 0 ? 'text-zinc-400' : 'text-zinc-700')}>
          <FileText className="h-3 w-3" aria-hidden />
          <span className="w-5 text-center">{fmtCount(reads)}</span>
        </span>
        <span className={cn('inline-flex w-12 items-center gap-1', searches > 0 ? 'text-zinc-400' : 'text-zinc-700')}>
          <Search className="h-3 w-3" aria-hidden />
          <span className="w-5 text-center">{fmtCount(searches)}</span>
        </span>
        <span className={cn('inline-flex w-12 items-center gap-1', others > 0 ? 'text-zinc-400' : 'text-zinc-700')}>
          <Wrench className="h-3 w-3" aria-hidden />
          <span className="w-5 text-center">{fmtCount(others)}</span>
        </span>
      </span>
      {runningHere ? (
        <Loader2 className="ml-auto h-3 w-3 animate-spin text-zinc-500" aria-hidden />
      ) : null}
    </button>
  )

  return (
    <div className="py-0.5">
      {trigger}
      {disableMotion ? (
        open ? list : null
      ) : (
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.15 }}
              className="overflow-hidden"
            >
              {list}
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  )
}

export function ToolUseLogPanel({ steps, disableMotion = false }: ToolUseLogPanelProps) {
  const [open, setOpen] = useState(false)
  const filtered = useMemo(() => filterTaskTimelineNoise(steps), [steps])
  const rows = useMemo(() => filtered.map(formatToolLogRow), [filtered])
  const bundled = useMemo(() => bundleConsecutiveToolRows(rows), [rows])
  const summary = useMemo(() => calcToolLogSummary(rows), [rows])
  const anyRunning = useMemo(() => filtered.some((s) => s.status === 'running'), [filtered])

  if (filtered.length === 0) return null

  const renderBlock = (pack: ToolLogBundledRow) => {
    if (pack.rows.length >= 2) {
      return <NestedBundlePanel key={pack.rows[0]!.id} pack={pack} disableMotion={disableMotion} />
    }
    const r = pack.rows[0]!
    return <LogLineWithTooltip key={r.id} row={r} />
  }

  const list = (
    <div
      className={cn(
        'mt-2 rounded-md border border-zinc-800 bg-zinc-950',
        'min-w-[280px] max-w-[480px] max-h-[260px] overflow-y-auto overflow-x-hidden',
        'px-3 py-2.5 font-mono text-[11.5px] leading-snug text-zinc-500 antialiased shadow-inner'
      )}
    >
      {bundled.map((pack) => renderBlock(pack))}
    </div>
  )

  return (
    <div className="mt-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex w-full min-w-[200px] max-w-[480px] items-center justify-between gap-3',
          'rounded-md border border-transparent py-1.5 px-2',
          'text-left text-xs transition-colors',
          'hover:border-zinc-700 hover:bg-zinc-800/50 hover:text-zinc-300',
          'dark:text-zinc-400 dark:hover:text-zinc-200'
        )}
      >
        {/* 等宽展示 3 类信息：读取 | 搜索 | 其他 */}
        <span className="inline-flex items-center gap-2 font-mono tabular-nums">
          {anyRunning ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-zinc-400" aria-hidden />
          ) : null}

          <span
            className={cn(
              'inline-flex w-14 items-center gap-1',
              summary.reads > 0 ? 'text-zinc-300' : 'text-zinc-600'
            )}
            title={`${summary.reads} 次读取`}
          >
            <FileText className="h-3.5 w-3.5" aria-hidden />
            <span className="w-5 text-center">{fmtCount(summary.reads)}</span>
          </span>

          <span
            className={cn(
              'inline-flex w-14 items-center gap-1',
              summary.searches > 0 ? 'text-zinc-300' : 'text-zinc-600'
            )}
            title={`${summary.searches} 次搜索${summary.searchBrand ? ` · ${summary.searchBrand}` : ''}`}
          >
            <Search className="h-3.5 w-3.5" aria-hidden />
            <span className="w-5 text-center">{fmtCount(summary.searches)}</span>
          </span>

          <span
            className={cn(
              'inline-flex w-14 items-center gap-1',
              summary.others > 0 ? 'text-zinc-300' : 'text-zinc-600'
            )}
            title={`${summary.others} 其他`}
          >
            <Wrench className="h-3.5 w-3.5" aria-hidden />
            <span className="w-5 text-center">{fmtCount(summary.others)}</span>
          </span>
        </span>

        <ChevronDown
          className={cn('h-3.5 w-3.5 shrink-0 opacity-60 transition-transform', open && 'rotate-180')}
          aria-hidden
        />
      </button>

      {disableMotion ? (
        open ? list : null
      ) : (
        <AnimatePresence initial={false}>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="overflow-hidden"
            >
              {list}
            </motion.div>
          )}
        </AnimatePresence>
      )}
    </div>
  )
}
