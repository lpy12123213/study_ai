import { useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, Download, Loader2, Plus, Share2, Trash2, Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { ShareLinkDialog } from '@/components/shared/ShareLinkDialog'
import * as templatesApi from '@/api/templates'

function downloadJson(filename: string, payload: unknown) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

function toJsonText(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2)
  } catch {
    return '{}'
  }
}

export default function TemplatesPage() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [typeFilter, setTypeFilter] = useState('study_materials')

  const { data: templates = [], isLoading, error } = useQuery({
    queryKey: ['templates', typeFilter],
    queryFn: () => templatesApi.listTemplates({ type: typeFilter, limit: 200 }),
  })

  const [editOpen, setEditOpen] = useState(false)
  const [editing, setEditing] = useState<templatesApi.UserTemplate | null>(null)
  const [name, setName] = useState('')
  const [bodyText, setBodyText] = useState('{}')
  const [shareTemplateId, setShareTemplateId] = useState<number | null>(null)
  const [editError, setEditError] = useState<unknown>(null)

  const saveMutation = useMutation({
    mutationFn: async (input: { id?: number; type: string; name: string; body: Record<string, unknown> }) => {
      if (input.id) {
        return await templatesApi.updateTemplate(input.id, { name: input.name, type: input.type, body: input.body })
      }
      return await templatesApi.createTemplate({ type: input.type, name: input.name, body: input.body })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      queryClient.invalidateQueries({ queryKey: ['templates', typeFilter] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => templatesApi.deleteTemplate(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['templates'] })
      queryClient.invalidateQueries({ queryKey: ['templates', typeFilter] })
    },
  })

  const openCreate = () => {
    setEditing(null)
    setName('')
    setBodyText('{}')
    setEditError(null)
    setEditOpen(true)
  }

  const openEdit = (tpl: templatesApi.UserTemplate) => {
    setEditing(tpl)
    setName(String(tpl.name || ''))
    setBodyText(toJsonText(tpl.body))
    setEditError(null)
    setEditOpen(true)
  }

  const save = async () => {
    setEditError(null)
    let body: Record<string, unknown> = {}
    try {
      const parsed = JSON.parse(bodyText || '{}')
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) body = parsed as Record<string, unknown>
    } catch (e) {
      setEditError(e)
      return
    }

    try {
      await saveMutation.mutateAsync({ id: editing?.id, type: typeFilter, name: name.trim(), body })
      setEditOpen(false)
    } catch (e) {
      setEditError(e)
    }
  }

  const exportAll = async () => {
    const all = await templatesApi.exportTemplates({ type: typeFilter })
    downloadJson(`templates-${typeFilter}.json`, { templates: all })
  }

  const importFromFile = async (file: File) => {
    const text = await file.text()
    const payload = JSON.parse(text || '{}') as any
    const list = Array.isArray(payload?.templates) ? payload.templates : Array.isArray(payload) ? payload : []
    const created = await templatesApi.importTemplates(list as templatesApi.UserTemplate[])
    return created
  }

  const typeLabel = useMemo(() => {
    const map: Record<string, string> = {
      study_materials: '自学资料',
      paper_compose: '蓝图组卷',
      lesson_plan: '教案',
      deepthink: '深度解题',
      other: '其他',
    }
    return map[typeFilter] || typeFilter
  }, [typeFilter])

  return (
    <div className="h-full flex flex-col overflow-hidden bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10">
        <div className="flex items-center gap-2 font-semibold">模板库</div>
        <div className="flex items-center gap-2">
          <Select value={typeFilter} onValueChange={setTypeFilter}>
            <SelectTrigger className="w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="study_materials">自学资料</SelectItem>
              <SelectItem value="paper_compose">蓝图组卷</SelectItem>
              <SelectItem value="lesson_plan">教案</SelectItem>
              <SelectItem value="deepthink">深度解题</SelectItem>
              <SelectItem value="other">其他</SelectItem>
            </SelectContent>
          </Select>
          <Button type="button" variant="outline" size="sm" onClick={exportAll} disabled={isLoading}>
            <Download className="h-4 w-4 mr-2" />
            导出
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/json,.json"
            className="hidden"
            onChange={async (e) => {
              const f = e.target.files?.[0]
              if (!f) return
              try {
                await importFromFile(f)
              } finally {
                e.target.value = ''
              }
            }}
          />
          <Button type="button" variant="outline" size="sm" onClick={() => fileInputRef.current?.click()}>
            <Upload className="h-4 w-4 mr-2" />
            导入
          </Button>
          <Button type="button" size="sm" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-2" />
            新建
          </Button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-auto p-6">
        <div className="max-w-4xl mx-auto space-y-3">
          {error && <ErrorNotice error={error} />}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          )}
          {!isLoading && !error && templates.length === 0 && (
            <Card className="p-6">
              <div className="text-sm text-muted-foreground">暂无 {typeLabel} 模板。</div>
              <div className="text-xs text-muted-foreground mt-2">
                你可以在模板内容中使用占位符（例如 {'{subject}'} / {'{grade}'}），在应用时用当前表单值自动替换。
              </div>
            </Card>
          )}

          {templates.map((t) => (
            <Card key={t.id} className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium truncate">{t.name || `模板 #${t.id}`}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    type: <span className="font-mono">{t.template_type}</span> · id: <span className="font-mono">{t.id}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <Button type="button" size="sm" variant="outline" onClick={() => openEdit(t)}>
                    编辑
                  </Button>
                  <Button type="button" size="sm" variant="outline" onClick={() => setShareTemplateId(t.id)}>
                    <Share2 className="h-4 w-4 mr-2" />
                    分享
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="destructive"
                    onClick={() => {
                      if (confirm('确定删除该模板吗？')) deleteMutation.mutate(t.id)
                    }}
                    disabled={deleteMutation.isPending}
                  >
                    <Trash2 className="h-4 w-4 mr-2" />
                    删除
                  </Button>
                </div>
              </div>

              <details className="mt-3">
                <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground select-none">
                  查看内容
                </summary>
                <pre className="mt-2 max-h-72 overflow-auto rounded-md bg-muted/30 border border-border/60 p-3 text-xs">
                  {toJsonText(t.body)}
                </pre>
              </details>
            </Card>
          ))}
        </div>
      </div>

      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle>{editing ? '编辑模板' : '新建模板'}</DialogTitle>
          </DialogHeader>

          <div className="space-y-3">
            {Boolean(editError) && <ErrorNotice error={editError} />}
            <div className="space-y-1.5">
              <div className="text-sm font-medium">名称</div>
              <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="给模板起个名字" />
            </div>
            <div className="space-y-1.5">
              <div className="text-sm font-medium flex items-center gap-2">
                内容（JSON）
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    await navigator.clipboard.writeText(bodyText)
                  }}
                >
                  <Copy className="h-3.5 w-3.5 mr-1.5" />
                  复制
                </Button>
              </div>
              <Textarea value={bodyText} onChange={(e) => setBodyText(e.target.value)} className="min-h-72 font-mono text-xs" />
            </div>
            <div className="flex items-center justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setEditOpen(false)}>
                取消
              </Button>
              <Button type="button" onClick={save} disabled={saveMutation.isPending}>
                {saveMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : '保存'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <ShareLinkDialog
        open={shareTemplateId != null}
        onOpenChange={(v) => !v && setShareTemplateId(null)}
        itemType="template"
        itemId={String(shareTemplateId || '')}
        title={`模板 #${shareTemplateId || ''}`}
      />
    </div>
  )
}
