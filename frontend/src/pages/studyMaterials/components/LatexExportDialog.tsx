import { Loader2 } from 'lucide-react'
import { resolveApiResourceUrl } from '@/api/client'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { StudyMaterialsController } from '@/pages/studyMaterials/hooks/useStudyMaterialsController'
import type { LatexLessonPlanOption } from '@/pages/studyMaterials/types'

function formatLatexOptionLabel(opt: LatexLessonPlanOption): string {
  const source = opt.sourceType === 'study_materials' ? '自学资料' : '教案'
  const title = opt.title || source
  const extras: string[] = []
  if (opt.subject) extras.push(opt.subject)
  if (opt.grade) extras.push(opt.grade)
  return `${source}：${title}${extras.length > 0 ? ` · ${extras.join(' · ')}` : ''}`
}

export function LatexExportDialog({ controller }: { controller: StudyMaterialsController }) {
  const {
    latexDialogOpen,
    setLatexDialogOpen,
    latexLessonPlanId,
    handlePickLessonPlanMarkdown,
    latexIsConverting,
    latexIsLoadingSource,
    latexLessonPlanOptions,
    latexFileName,
    latexTopic,
    setLatexTopic,
    latexSubject,
    setLatexSubject,
    latexMarkdown,
    setLatexMarkdown,
    clearLatexLessonPlanSelection,
    latexProgressStage,
    latexProgressPercent,
    latexError,
    latexTexUrl,
    latexTexFilename,
    latexTexText,
    latexNotice,
    handleCopyLatex,
    handleConvertToLatex,
  } = controller

  const options = latexLessonPlanOptions.filter((opt) => opt.id.trim().length > 0)
  const canClear = Boolean(latexLessonPlanId || latexMarkdown)

  return (
    <Dialog open={latexDialogOpen} onOpenChange={setLatexDialogOpen}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-auto">
        <DialogHeader>
          <DialogTitle>Markdown → LaTeX</DialogTitle>
          <DialogDescription>从已生成的 Markdown（自学资料/教案）中选择，AI 将转换为可下载的 LaTeX（.tex）。</DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">选择 Markdown 来源</div>
              <Select
                value={latexLessonPlanId}
                onValueChange={(v) => void handlePickLessonPlanMarkdown(v)}
                disabled={latexIsConverting || latexIsLoadingSource}
              >
                <SelectTrigger>
                  <SelectValue placeholder={options.length > 0 ? '请选择…' : '暂无可选 Markdown（请先生成内容）'} />
                </SelectTrigger>
                <SelectContent>
                  {options.length === 0 ? (
                    <SelectItem value="__empty" disabled>
                      暂无可选 Markdown（请先生成内容）
                    </SelectItem>
                  ) : (
                    options.map((opt) => (
                      <SelectItem key={opt.id} value={opt.id}>
                        {formatLatexOptionLabel(opt)}
                      </SelectItem>
                    ))
                  )}
                </SelectContent>
              </Select>
              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground truncate">{latexFileName ? `文件：${latexFileName}` : null}</div>
                {latexIsLoadingSource ? (
                  <div className="flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    加载中
                  </div>
                ) : null}
              </div>
            </div>

            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">标题（可选）</div>
              <Input
                value={latexTopic}
                onChange={(e) => setLatexTopic(e.target.value)}
                placeholder="用于 LaTeX 标题（可选）"
                disabled={latexIsConverting}
              />
            </div>

            <div className="space-y-1.5">
              <div className="text-xs font-medium text-muted-foreground">学科（可选）</div>
              <Input
                value={latexSubject}
                onChange={(e) => setLatexSubject(e.target.value)}
                placeholder="例如：高中数学 / 大学物理"
                disabled={latexIsConverting}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-muted-foreground">Markdown 内容</div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-xs"
                onClick={clearLatexLessonPlanSelection}
                disabled={latexIsConverting || latexIsLoadingSource || !canClear}
              >
                清除选择
              </Button>
            </div>
            <Textarea
              value={latexMarkdown}
              onChange={(e) => setLatexMarkdown(e.target.value)}
              className="min-h-[180px] font-mono text-xs"
              placeholder="可从上方选择加载，也可直接粘贴/编辑 Markdown"
              disabled={latexIsConverting || latexIsLoadingSource}
            />
          </div>

          {latexIsConverting && (
            <div className="rounded-xl border border-border bg-muted/20 p-3 space-y-2">
              <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <div className="truncate">{latexProgressStage || '转换中…'}</div>
                <div className="shrink-0">{latexProgressPercent}%</div>
              </div>
              <Progress value={latexProgressPercent} className="h-2" />
            </div>
          )}

          {latexError && (
            <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-3 text-sm text-destructive flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-destructive shrink-0" />
              {latexError}
            </div>
          )}

          {latexTexUrl && (
            <div className="rounded-xl border border-border bg-muted/20 p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div className="text-xs text-muted-foreground">
                  {latexTexFilename ? `已生成：${latexTexFilename}` : '已生成 LaTeX'}
                  {latexNotice ? <span className="ml-2">（{latexNotice}）</span> : null}
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-8 px-2 text-xs"
                    onClick={handleCopyLatex}
                    disabled={!latexTexText}
                  >
                    复制 LaTeX
                  </Button>
                  <Button asChild size="sm" className="h-8 px-2 text-xs">
                    <a
                      href={resolveApiResourceUrl(latexTexUrl)}
                      target="_blank"
                      rel="noreferrer"
                      download={latexTexFilename || ''}
                    >
                      下载 .tex
                    </a>
                  </Button>
                </div>
              </div>
              <Textarea
                value={latexTexText}
                readOnly
                className="min-h-[220px] font-mono text-xs"
                placeholder="LaTeX 输出将显示在这里"
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => setLatexDialogOpen(false)} disabled={latexIsConverting}>
            关闭
          </Button>
          <Button
            type="button"
            onClick={handleConvertToLatex}
            disabled={latexIsConverting || latexIsLoadingSource || !latexMarkdown.trim()}
          >
            {latexIsConverting && <Loader2 className="h-4 w-4 animate-spin" />}
            开始转换
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

