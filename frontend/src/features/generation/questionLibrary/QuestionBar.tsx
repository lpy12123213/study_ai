import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, ShoppingCart, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import { exportQuestionToBasket } from '@/api/questionLibrary'
import { useCreatePaper } from '@/hooks/usePapers'
import { useQuestionBarStore } from '@/stores/useQuestionBarStore'
import { useNotificationStore } from '@/stores/useNotificationStore'
import * as tasksApi from '@/api/tasks'

function modeLabel(mode: string | null | undefined): string {
  if (mode === 'zujuan') return '组卷网试题栏'
  if (mode === 'local') return '本地试题栏'
  return '试题栏'
}

function defaultPaperName(mode: string | null | undefined): string {
  const d = new Date()
  const stamp = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}-${String(d.getHours()).padStart(2, '0')}${String(d.getMinutes()).padStart(2, '0')}`
  return `${modeLabel(mode)}-${stamp}`
}

export function QuestionBar() {
  const navigate = useNavigate()
  const pushToast = useNotificationStore((s) => s.pushToast)
  const { mutateAsync: createPaper, isPending: isCreatingPaper } = useCreatePaper()

  const sourceMode = useQuestionBarStore((s) => s.sourceMode)
  const items = useQuestionBarStore((s) => s.items)
  const clear = useQuestionBarStore((s) => s.clear)
  const removeItem = useQuestionBarStore((s) => s.removeItem)

  const [expanded, setExpanded] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [includeAnswer, setIncludeAnswer] = useState(true)
  const [includeAnalysis, setIncludeAnalysis] = useState(true)

  const count = items.length
  const canExport = count > 0 && !isExporting && !isCreatingPaper

  const questionIds = useMemo(() => items.map((x) => String(x.questionId || '').trim()).filter(Boolean), [items])

  if (count === 0) return null

  const exportToZujuanBasket = async () => {
    if (!canExport) return
    if (sourceMode !== 'zujuan') return
    setIsExporting(true)
    try {
      let okCount = 0
      let lastBasketUrl = ''
      for (const qid of questionIds) {
        const res = await exportQuestionToBasket(qid)
        if (res?.success) {
          okCount += 1
          const url = String(res?.basket_url || '').trim()
          if (url) lastBasketUrl = url
        }
      }
      if (okCount > 0) {
        pushToast({
          id: `qb-export-zujuan-${Date.now()}`,
          title: `已加入组卷网题篮：${okCount}/${questionIds.length}`,
          status: 'completed',
        })
        if (lastBasketUrl) {
          window.open(lastBasketUrl, '_blank', 'noopener,noreferrer')
        }
        clear()
      } else {
        pushToast({
          id: `qb-export-zujuan-failed-${Date.now()}`,
          title: '加入组卷网题篮失败',
          status: 'failed',
        })
      }
    } catch (err: any) {
      pushToast({ id: `qb-export-zujuan-error-${Date.now()}`, title: err?.message || '导出失败', status: 'failed' })
    } finally {
      setIsExporting(false)
    }
  }

  const saveAsPaper = async () => {
    if (!canExport) return
    const name = defaultPaperName(sourceMode)
    try {
      const res = await createPaper({ name, questionIds })
      if (res?.success && res.paperId) {
        const { taskId } = await tasksApi.exportPaperTask(res.paperId, {
          format: 'docx',
          includeStem: true,
          includeAnswer,
          includeAnalysis,
        })
        if (taskId) {
          pushToast({ id: `qb-export-${taskId}`, title: '已加入导出队列', taskId, status: 'running' })
          clear()
          navigate('/exports')
          return
        }
        pushToast({ id: `qb-export-failed-${Date.now()}`, title: '导出任务创建失败', status: 'failed' })
        return
      }
      pushToast({ id: `qb-paper-failed-${Date.now()}`, title: res?.message || '创建试卷失败', status: 'failed' })
    } catch (err: any) {
      pushToast({ id: `qb-paper-error-${Date.now()}`, title: err?.message || '创建试卷失败', status: 'failed' })
    }
  }

  return (
    <div className={cn('aurora-question-basket border-t', expanded ? 'h-[240px]' : 'h-[54px]')}>
      <div className="h-[54px] px-4 flex items-center justify-between gap-3">
        <button
          type="button"
          className="flex-1 min-w-0 text-left"
          onClick={() => setExpanded((v) => !v)}
        >
          <div className="flex items-center gap-2 min-w-0">
            <ShoppingCart className="h-4 w-4 text-primary shrink-0" />
            <div className="text-sm font-medium truncate">{modeLabel(sourceMode)}</div>
            <div className="text-xs text-muted-foreground shrink-0">{count} 题</div>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            加入第一道题后来源模式锁定；清空后可重新选择。
          </div>
        </button>

        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="h-9 w-9"
          onClick={() => {
            if (confirm('确定清空试题栏吗？')) clear()
          }}
          aria-label="清空试题栏"
        >
          <Trash2 className="h-4 w-4" />
        </Button>

        <Button type="button" variant="ghost" size="icon" className="h-9 w-9" onClick={() => setExpanded((v) => !v)}>
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
        </Button>
      </div>

      {expanded && (
        <div className="h-[calc(240px-54px)] border-t border-border">
          <ScrollArea className="h-full">
            <div className="p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">导出</div>
                <div className="flex items-center gap-2">
                  {sourceMode === 'zujuan' ? (
                    <Button type="button" size="sm" disabled={!canExport} onClick={exportToZujuanBasket}>
                      {isExporting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                      加入组卷网题篮
                    </Button>
                  ) : (
                    <Button type="button" size="sm" disabled={!canExport} onClick={saveAsPaper}>
                      {isCreatingPaper ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : null}
                      导出 DOCX
                    </Button>
                  )}
                </div>
              </div>

              {sourceMode !== 'zujuan' && (
                <div className="aurora-question-answer flex flex-wrap items-center gap-4 p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <Switch checked={includeAnswer} onCheckedChange={(v: boolean) => setIncludeAnswer(Boolean(v))} />
                    <div className="text-xs text-muted-foreground select-none">包含答案</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch checked={includeAnalysis} onCheckedChange={(v: boolean) => setIncludeAnalysis(Boolean(v))} />
                    <div className="text-xs text-muted-foreground select-none">包含解析</div>
                  </div>
                </div>
              )}

              <div className="text-xs text-muted-foreground">题目列表</div>
              <div className="space-y-2">
                {items.map((it) => (
                  <div key={it.questionId} className="aurora-question-card flex items-start justify-between gap-2 p-2">
                    <div className="min-w-0">
                      <div className="text-xs font-mono text-muted-foreground truncate">{it.questionId}</div>
                      {it.stem && <div className="text-sm text-foreground/80 line-clamp-2 mt-1">{it.stem}</div>}
                    </div>
                    <Button type="button" variant="ghost" size="sm" className="h-8 px-2" onClick={() => removeItem(it.questionId)}>
                      移除
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          </ScrollArea>
        </div>
      )}
    </div>
  )
}
