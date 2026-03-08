import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, Package, RotateCcw, X, FolderDown } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { downloadObjectUrl } from '@/api/client'
import * as tasksApi from '@/api/tasks'
import * as exportsApi from '@/api/exports'
import { cn, formatDate } from '@/lib/utils'

type ExportStatusFilter = 'all' | 'running' | 'failed' | 'completed'

function isExportTaskType(taskType: string): boolean {
  const t = String(taskType || '').trim()
  return t.startsWith('export_')
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
    refetchInterval: 5000,
  })

  const exportTasks = tasksResp || []

  const { data: files = [], isLoading: isLoadingFiles, error: filesError } = useQuery({
    queryKey: ['generatedFiles'],
    queryFn: () => exportsApi.listGeneratedFiles({ limit: 200, offset: 0 }),
    refetchInterval: 8000,
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['generatedFiles'] }),
  })

  const selectedList = useMemo(() => Object.entries(selectedFiles).filter(([, v]) => v).map(([k]) => k), [selectedFiles])

  const toggleFile = (fn: string) => {
    setSelectedFiles((prev) => ({ ...prev, [fn]: !prev[fn] }))
  }

  const doZipDownload = async () => {
    if (selectedList.length === 0) return
    const res = await zipFiles.mutateAsync(selectedList)
    const url = String((res as any)?.url || '')
    if (url) await downloadByUrl(url)
  }

  const taskDownloadUrls = (task: tasksApi.UnifiedTask): string[] => {
    const result = (task.result || {}) as any
    const urls: string[] = []
    if (typeof result?.url === 'string' && result.url) urls.push(result.url)
    if (typeof result?.pdf_url === 'string' && result.pdf_url) urls.push(result.pdf_url)
    if (typeof result?.tex_url === 'string' && result.tex_url) urls.push(result.tex_url)
    if (typeof result?.pdfUrl === 'string' && result.pdfUrl) urls.push(result.pdfUrl)
    if (typeof result?.texUrl === 'string' && result.texUrl) urls.push(result.texUrl)
    if (typeof result?.pdf_url === 'string') urls.push(result.pdf_url)
    return Array.from(new Set(urls.filter(Boolean)))
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2 font-semibold">
          <FolderDown className="h-4 w-4 text-primary" />
          导出中心
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
        <Card className="flex flex-col min-h-0">
          <div className="p-4 border-b border-border">
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
                <div key={t.id} className="rounded-lg border p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-medium text-sm truncate">{t.title}</div>
                      <div className="text-xs text-muted-foreground mt-1">
                        <span className={cn(
                          'inline-flex items-center rounded px-1.5 py-0.5',
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
                          {String((t.error as any)?.message || (t.error as any)?.error || '导出失败')}
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

        <Card className="flex flex-col min-h-0">
          <div className="p-4 border-b border-border flex items-start justify-between gap-3">
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
                <div key={f.filename} className="rounded-lg border p-3">
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
                          <div className="text-xs text-muted-foreground mt-1">过期：{f.expires_at}</div>
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
          <div className="p-4 text-xs text-muted-foreground">
            提示：下载会使用鉴权请求生成临时链接，避免泄露文件给其他用户。
          </div>
        </Card>
      </div>
    </div>
  )
}
