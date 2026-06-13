import { Loader2, Wand2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import type { Subject } from '@/types'

export const DIFFICULTY_ANY = '__any__'

export interface GenerateConfigCardProps {
  subjects: Subject[] | undefined
  subject: string
  onSubjectChange: (value: string) => void
  topic: string
  onTopicChange: (value: string) => void
  difficulty: string
  onDifficultyChange: (value: string) => void
  questionType: string
  onQuestionTypeChange: (value: string) => void
  count: string
  onCountChange: (value: string) => void
  useStudyArchive: boolean
  onUseStudyArchiveChange: (value: boolean) => void
  canGenerate: boolean
  isRunning: boolean
  onRun: () => void
}

export function GenerateConfigCard({
  subjects,
  subject,
  onSubjectChange,
  topic,
  onTopicChange,
  difficulty,
  onDifficultyChange,
  questionType,
  onQuestionTypeChange,
  count,
  onCountChange,
  useStudyArchive,
  onUseStudyArchiveChange,
  canGenerate,
  isRunning,
  onRun,
}: GenerateConfigCardProps) {
  return (
    <Card className="aurora-ai-card overflow-hidden">
      <CardHeader>
        <div className="font-mono text-xs uppercase tracking-[0.18em] text-muted-foreground">Prompt control</div>
        <CardTitle className="text-base">生成配置</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
          <div className="md:col-span-3">
            <div className="text-xs text-muted-foreground mb-2">学科</div>
            <Select value={subject} onValueChange={onSubjectChange}>
              <SelectTrigger className="h-9 bg-background/45">
                <SelectValue placeholder="选择学科" />
              </SelectTrigger>
              <SelectContent>
                {(subjects || []).map((s) => (
                  <SelectItem key={s.code} value={s.code}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-5">
            <div className="text-xs text-muted-foreground mb-2">主题 / 知识点</div>
            <Input value={topic} onChange={(e) => onTopicChange(e.target.value)} placeholder="例如：函数 单调性" className="h-9 bg-background/45" />
          </div>
          <div className="md:col-span-2">
            <div className="text-xs text-muted-foreground mb-2">难度</div>
            <Select value={difficulty} onValueChange={onDifficultyChange}>
              <SelectTrigger className="h-9 bg-background/45">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DIFFICULTY_ANY}>不限</SelectItem>
                <SelectItem value="简单">简单</SelectItem>
                <SelectItem value="中等">中等</SelectItem>
                <SelectItem value="困难">困难</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="md:col-span-2">
            <div className="text-xs text-muted-foreground mb-2">数量</div>
            <Input value={count} onChange={(e) => onCountChange(e.target.value)} placeholder="5" className="h-9 bg-background/45" />
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-end">
          <div className="md:col-span-8">
            <div className="text-xs text-muted-foreground mb-2">题型（可选）</div>
            <Input
              value={questionType}
              onChange={(e) => onQuestionTypeChange(e.target.value)}
              placeholder="例如：选择题 / 填空题 / 解答题"
              className="h-9 bg-background/45"
            />
          </div>
          <div className="md:col-span-4">
            <div className="aurora-ai-probe flex items-center justify-between gap-3 p-3">
              <div className="min-w-0">
                <div className="text-sm font-medium">使用自学资料</div>
                <div className="text-xs text-muted-foreground">从 StudyArchive 提取上下文，提高生成质量</div>
              </div>
              <Switch checked={useStudyArchive} onCheckedChange={(v: boolean) => onUseStudyArchiveChange(Boolean(v))} />
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button type="button" onClick={onRun} disabled={!canGenerate}>
            <Wand2 className="h-4 w-4 mr-2" />
            开始生成
          </Button>
          {isRunning && (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              生成中…
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
