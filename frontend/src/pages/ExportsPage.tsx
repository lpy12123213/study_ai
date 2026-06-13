import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, Package, RotateCcw, X, FolderDown, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { downloadObjectUrl } from '@/api/client'
import * as tasksApi from '@/api/tasks'
import * as exportsApi from '@/api/exports'
import { cn, formatDate } from '@/lib/utils'
import { readString, readStringFrom } from '@/lib/record'
import { DEFAULT_RESOURCE_REFETCH_INTERVAL_MS, RUNNING_TASKS_REFETCH_INTERVAL_MS } from '@/hooks/useRunningTasks'

type ExportStatusFilter = 'all' | 'running' | 'failed' | 'completed'

function isExportTaskType(taskType: string): boolean {
  const t = String(taskType || '').trim()
  return t.startsWith('export_') || t === 'knowledge_video'
}

async function downloadByUrl(url: string): Promise<void> {
  const { objectUrl, revoke, filename } = await downloadObjectUrl(url)
  const a = document.createElement('a')
  a.href = objectUrl
  a.download = filename || ''
  a.click()
  window.setTimeout(revoke, 60_000)
}

export default function ExportsPage() {
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState<ExportStatusFilter>('all')
  const [selectedFiles, setSelectedFiles] = useState<Record<string, boolean>>({})

  const { data: tasksResp, isLoading: isLoadingTasks, error: tasksError } = useQuery({
    queryKey: ['exportTasks', statusFilter],
    queryFn: async () => {
      const res = await tasksApi.listTasks({ limit: 200 })
      const tasks = (res.tasks || []).filter((t) => isExportTaskType(String(t.task_type || '')))
      if (statusFilter === 'all') return tasks
      return tasks.filter((t) => String(t.status || '') === statusFilter)
    },
    refetchInterval: RUNNING_TASKS_REFETCH_INTERVAL_MS,
  })

  const exportTasks = tasksResp || []

  const { data: files = [], isLoading: isLoadingFiles, error: filesError } = useQuery({
    queryKey: ['generatedFiles'],
    queryFn: () => exportsApi.listGeneratedFiles({ limit: 200, offset: 0 }),
    refetchInterval: DEFAULT_RESOURCE_REFETCH_INTERVAL_MS,
  })

  const cancelTask = useMutation({
    mutationFn: (taskId: string) => tasksApi.cancelTask(taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['exportTasks'] }),
  })

  const retryTask = useMutation({
    mutationFn: (taskId: string) => tasksApi.retryTask(taskId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['exportTasks'] }),
  })

  const zipFiles = useMutation({
    mutationFn: (filenames: string[]) => exportsApi.zipGeneratedFiles(filenames),
    onSuccess: () => {
      setSelectedFiles({})
      queryClient.invalidateQueries({ queryKey: ['generatedFiles'] })
    },
  })

  const currentFilenameSet = useMemo(() => new Set(files.map((f) => f.filename)), [files])
  const selectedList = useMemo(
    () => Object.entries(selectedFiles).filter(([k, v]) => v && currentFilenameSet.has(k)).map(([k]) => k),
    [currentFilenameSet, selectedFiles],
  )
  const exportStats = useMemo(() => {
    const running = exportTasks.filter((task) => String(task.status || '') === 'running').length
    const failed = exportTasks.filter((task) => String(task.status || '') === 'failed').length
    const completed = exportTasks.filter((task) => String(task.status || '') === 'completed').length
    return [
      { label: '导出任务', value: `${exportTasks.length}` },
      { label: '运行中', value: `${running}` },
      { label: '失败', value: `${failed}` },
      { label: '文件数', value: `${files.length}` },
      { label: '已选文件', value: `${selectedList.length}` },
      { label: '已完成', value: `${completed}` },
    ]
  }, [exportTasks, files.length, selectedList.length])

  useEffect(() => {
    setSelectedFiles((prev) => {
      const next = Object.fromEntries(Object.entries(prev).filter(([k, v]) => v && currentFilenameSet.has(k)))
      return Object.keys(next).length === Object.keys(prev).length ? prev : next
    })
  }, [currentFilenameSet])

  const toggleFile = (fn: string) => {
    setSelectedFiles((prev) => ({ ...prev, [fn]: !prev[fn] }))
  }

  const doZipDownload = async () => {
    if (selectedList.length === 0) return
    const res = await zipFiles.mutateAsync(selectedList.filter((filename) => currentFilenameSet.has(filename)))
    const url = String(res?.url || '')
    if (url) await downloadByUrl(url)
  }

  const taskDownloadUrls = (task: tasksApi.UnifiedTask): string[] => {
    const result = task.result || {}
    const urls = [
      readString(result, 'url'),
      readString(result, 'video_url'),
      readString(result, 'subtitle_url'),
      readString(result, 'script_url'),
      readString(result, 'pdf_url'),
      readString(result, 'tex_url'),
      readString(result, 'pdfUrl'),
      readString(result, 'texUrl'),
    ].filter(Boolean)
    return Array.from(new Set(urls))
  }

  return (
    <div className="aurora-exports-screen h-full flex flex-col overflow-hidden">
      <div className="aurora-exports-hero p-4 flex items-center justify-between sticky top-0 z-10">
        <div className="min-w-0">
          <div className="aurora-kicker">
            <Sparkles className="h-3.5 w-3.5" />
            Export Delivery Dock
          </div>
          <div className="mt-2 flex items-center gap-2 font-semibold">
            <FolderDown className="h-4 w-4 text-primary" />
            导出中心
          </div>
          <p className="mt-1 text-xs text-muted-foreground">汇总试卷、资料、视频等导出任务与已生成文件，支持单独下载和批量打包。</p>
        </div>
        <div className="aurora-exports-stat-grid">
          {exportStats.map((item) => (
            <div key={item.label} className="aurora-exports-stat">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </div>
          ))}
        </div>
        <div className="flex items-center gap-2">
          {(['all', 'running', 'failed', 'completed'] as ExportStatusFilter[]).map((s) => (
            <Button
              key={s}
              type="button"
              size="sm"
              variant={statusFilter === s ? 'default' : 'outline'}
              onClick={() => setStatusFilter(s)}
            >
              {s === 'all' ? '全部' : s === 'running' ? '进行中' : s === 'failed' ? '失败' : '已完成'}
            </Button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-2 gap-4 p-4 overflow-hidden">
        <Card className="aurora-exports-panel flex flex-col min-h-0">
          <div className="aurora-exports-panel-head p-4">
            <div className="font-medium">导出队列</div>
            <div className="text-xs text-muted-foreground mt-1">来自试卷/资料的导出任务（支持取消/重试）。</div>
          </div>
          <ScrollArea className="flex-1">
            <div className="p-4 space-y-3">
              {isLoadingTasks && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  加载中…
                </div>
              )}
              {Boolean(tasksError) && <ErrorNotice error={tasksError} />}
              {!isLoadingTasks && !tasksError && exportTasks.length === 0 && (
                <div className="text-sm text-muted-foreground">暂无导出任务。</div>
              )}

              {exportTasks.map((t) => (
                <div key={t.id} className="aurora-exports-task rounded-lg p-3" data-status={String(t.status || '')}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium text-sm truncate">{t.title}</div>
                      <div className="text-xs text-muted-foreground mt-1">
                        <span className={cn(
                          'aurora-exports-status inline-flex items-center rounded px-1.5 py-0.5',
                          t.status === 'running' && 'bg-primary/10 text-primary',
                          t.status === 'failed' && 'bg-destructive/10 text-destructive',
                          t.status === 'completed' && 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
                        )}>
                          {String(t.status)}
                        </span>
                        <span className="ml-2">{formatDate(t.created_at)}</span>
                      </div>
                      {t.status === 'failed' && Boolean(t.error) && (
                        <div className="mt-2 text-xs text-destructive whitespace-pre-wrap break-words">
                          {readStringFrom(t.error, ['message', 'error']) || '导出失败'}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {t.status === 'running' && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => cancelTask.mutate(t.id)}
                          disabled={cancelTask.isPending}
                        >
                          <X className="h-4 w-4 mr-2" />
                          取消
                        </Button>
                      )}
                      {t.status === 'failed' && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          onClick={() => retryTask.mutate(t.id)}
                          disabled={retryTask.isPending}
                        >
                          <RotateCcw className="h-4 w-4 mr-2" />
                          重试
                        </Button>
                      )}
                      {t.status === 'completed' && (
                        <Button
                          type="button"
                          size="sm"
                          variant="default"
                          onClick={async () => {
                            const urls = taskDownloadUrls(t)
                            if (urls.length > 0) await downloadByUrl(urls[0])
                          }}
                        >
                          <Download className="h-4 w-4 mr-2" />
                          下载
                        </Button>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </Card>

        <Card className="aurora-exports-panel flex flex-col min-h-0">
          <div className="aurora-exports-panel-head p-4 flex items-start justify-between gap-3">
            <div>
              <div className="font-medium">导出文件</div>
              <div className="text-xs text-muted-foreground mt-1">所有已生成文件（可勾选打包下载）。</div>
            </div>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={selectedList.length === 0 || zipFiles.isPending}
              onClick={doZipDownload}
            >
              {zipFiles.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Package className="h-4 w-4 mr-2" />}
              打包下载 ({selectedList.length})
            </Button>
          </div>
          <ScrollArea className="flex-1">
            <div className="p-4 space-y-3">
              {isLoadingFiles && (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  加载中…
                </div>
              )}
              {Boolean(filesError) && <ErrorNotice error={filesError} />}
              {!isLoadingFiles && !filesError && files.length === 0 && (
                <div className="text-sm text-muted-foreground">暂无文件。</div>
              )}

              {files.map((f) => (
                <div key={f.filename} className="aurora-exports-file rounded-lg p-3">
                  <div className="flex items-start justify-between gap-3">
                    <label className="flex items-start gap-3 min-w-0 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={Boolean(selectedFiles[f.filename])}
                        onChange={() => toggleFile(f.filename)}
                        className="mt-1"
                      />
                      <div className="min-w-0">
                        <div className="font-mono text-xs break-all">{f.filename}</div>
                        <div className="text-xs text-muted-foreground mt-1">
                          {f.file_type} · {Math.round((f.bytes || 0) / 1024)} KB · {formatDate(f.created_at || '')}
                        </div>
                        {f.expires_at && (
                          <div className="text-xs text-muted-foreground mt-1">过期：{formatDate(f.expires_at)}</div>
                        )}
                      </div>
                    </label>

                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        await downloadByUrl(`/api/media/generated/${f.filename}`)
                      }}
                    >
                      <Download className="h-4 w-4 mr-2" />
                      下载
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
          <Separator />
          <div className="aurora-exports-foot p-4 text-xs text-muted-foreground">
            提示：下载会使用鉴权请求生成临时链接，避免泄露文件给其他用户。
          </div>
        </Card>
      </div>
    </div>
  )
}
