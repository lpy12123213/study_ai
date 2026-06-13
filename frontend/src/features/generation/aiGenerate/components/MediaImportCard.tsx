import { useMemo, useRef, useState, type ChangeEvent } from 'react'
import { FileImage, Loader2, Upload, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

export interface MediaImportCardProps {
  subject: string
  topic: string
  difficulty: string
  questionType: string
  isRunning: boolean
  onRun: (payload: { files: File[]; maxQuestions: number }) => void
}

function fileLabel(files: File[]): string {
  if (!files.length) return '未选择文件'
  if (files.length === 1) return files[0]?.name || '1 个文件'
  return `${files.length} 个文件`
}

export function MediaImportCard({
  subject,
  topic,
  difficulty,
  questionType,
  isRunning,
  onRun,
}: MediaImportCardProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [maxQuestions, setMaxQuestions] = useState('10')

  const canRun = useMemo(() => {
    if (!subject.trim()) return false
    return files.length > 0
  }, [files.length, subject])

  const selectFiles = (event: ChangeEvent<HTMLInputElement>) => {
    setFiles(Array.from(event.target.files || []))
  }

  const clearFiles = () => {
    setFiles([])
    if (inputRef.current) inputRef.current.value = ''
  }

  const run = () => {
    if (!canRun || isRunning) return
    const n = Number(maxQuestions)
    onRun({
      files,
      maxQuestions: Number.isFinite(n) ? Math.max(1, Math.min(30, Math.floor(n))) : 10,
    })
  }

  return (
    <Card className="aurora-ai-card overflow-hidden">
      <CardHeader>
        <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">Vision intake</div>
        <CardTitle className="text-base">图片/PDF 录入</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <input
          ref={inputRef}
          type="file"
          accept=".png,.jpg,.jpeg,.webp,.pdf,image/png,image/jpeg,image/webp,application/pdf"
          multiple
          className="hidden"
          onChange={selectFiles}
        />

        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
          <div className="md:col-span-7">
            <div className="text-xs text-muted-foreground mb-2">文件</div>
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => inputRef.current?.click()} className="h-9 gap-2">
                <FileImage className="h-4 w-4" />
                选择图片/PDF
              </Button>
              <div className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{fileLabel(files)}</div>
              {files.length > 0 && (
                <Button type="button" variant="ghost" size="icon" className="h-9 w-9" onClick={clearFiles}>
                  <X className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>

          <div className="md:col-span-2">
            <div className="text-xs text-muted-foreground mb-2">最多题数</div>
            <Input value={maxQuestions} onChange={(e) => setMaxQuestions(e.target.value)} className="h-9 bg-background/45" />
          </div>

          <div className="md:col-span-3">
            <Button type="button" onClick={run} disabled={!canRun || isRunning} className="h-9 w-full gap-2">
              {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
              开始录入
            </Button>
          </div>
        </div>

        <div className="aurora-ai-probe px-3 py-2 text-xs text-muted-foreground">
          {subject || '未选择学科'}
          {topic.trim() ? ` · ${topic.trim()}` : ''}
          {difficulty.trim() ? ` · ${difficulty.trim()}` : ''}
          {questionType.trim() ? ` · ${questionType.trim()}` : ''}
        </div>
      </CardContent>
    </Card>
  )
}
