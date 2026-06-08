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
import type { CanvasBoard } from '@/api/canvas'

interface ConflictDialogProps {
  open: boolean
  serverBoard: CanvasBoard | null
  onOpenChange: (open: boolean) => void
  onOverwrite: () => void
  onDiscardLocal: () => void
}

export function ConflictDialog({ open, serverBoard, onOpenChange, onOverwrite, onDiscardLocal }: ConflictDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-600" />
            保存冲突
          </DialogTitle>
          <DialogDescription>
            服务端已有 Revision {serverBoard?.revision ?? '-'}，请选择保留哪一版。
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onDiscardLocal}>
            放弃本地
          </Button>
          <Button type="button" onClick={onOverwrite}>
            覆盖服务端
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
