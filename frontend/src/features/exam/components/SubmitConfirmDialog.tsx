import { AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

interface SubmitConfirmDialogProps {
  open: boolean
  answeredCount: number
  totalCount: number
  isSubmitting?: boolean
  onOpenChange: (open: boolean) => void
  onConfirm: () => void
}

export function SubmitConfirmDialog({
  open,
  answeredCount,
  totalCount,
  isSubmitting,
  onOpenChange,
  onConfirm,
}: SubmitConfirmDialogProps) {
  const unanswered = Math.max(0, totalCount - answeredCount)
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>确认交卷</DialogTitle>
          <DialogDescription>
            已答 {answeredCount}/{totalCount} 题，交卷后将进入自动批改。
          </DialogDescription>
        </DialogHeader>
        {unanswered > 0 && (
          <div className="flex items-start gap-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            <AlertTriangle className="mt-0.5 h-4 w-4" />
            还有 {unanswered} 题未作答。
          </div>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            继续答题
          </Button>
          <Button type="button" onClick={onConfirm} disabled={isSubmitting}>
            确认交卷
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
