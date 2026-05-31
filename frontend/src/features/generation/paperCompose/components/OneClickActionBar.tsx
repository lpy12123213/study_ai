import { FileText, Square } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export interface OneClickActionBarProps {
  progress: number
  taskId: string
  subject: string
  isGenerating: boolean
  onStop: () => void
  onGenerate: () => void
}

export function OneClickActionBar({
  progress,
  taskId,
  subject,
  isGenerating,
  onStop,
  onGenerate,
}: OneClickActionBarProps) {
  return (
    <div className="flex items-center gap-3 pt-4 border-t border-border">
      <div className="flex-1 flex items-center gap-2">
        <Badge variant="secondary" className="font-normal">
          进度 {Math.round(progress)}%
        </Badge>
        {taskId ? (
          <Badge variant="outline" className="font-normal">
            task={taskId}
          </Badge>
        ) : null}
      </div>

      {isGenerating ? (
        <Button variant="destructive" onClick={onStop} className="w-32">
          <Square className="h-4 w-4 mr-2" />
          停止
        </Button>
      ) : (
        <Button
          onClick={onGenerate}
          disabled={!subject}
          className="w-32 bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
        >
          <FileText className="h-4 w-4 mr-2" />
          一键生成
        </Button>
      )}
    </div>
  )
}
