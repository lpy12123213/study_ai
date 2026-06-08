import { Loader2, RotateCcw, Save } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import type { CanvasBoardVersion } from '@/api/canvas'
import { formatDate, formatTime } from '@/lib/utils'

interface VersionsDrawerProps {
  open: boolean
  versions: CanvasBoardVersion[]
  loading: boolean
  creating: boolean
  restoringId?: number | null
  onOpenChange: (open: boolean) => void
  onCreateVersion: () => void
  onRestore: (versionId: number) => void
}

export function VersionsDrawer(props: VersionsDrawerProps) {
  return (
    <Sheet open={props.open} onOpenChange={props.onOpenChange}>
      <SheetContent className="flex w-[360px] flex-col p-0 sm:max-w-md">
        <SheetHeader className="border-b p-4">
          <SheetTitle>版本快照</SheetTitle>
        </SheetHeader>
        <div className="border-b p-4">
          <Button type="button" className="w-full" onClick={props.onCreateVersion} disabled={props.creating}>
            {props.creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            保存版本
          </Button>
        </div>
        <div className="min-h-0 flex-1 space-y-2 overflow-auto p-4">
          {props.loading ? (
            <div className="flex justify-center p-6">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : props.versions.length === 0 ? (
            <div className="rounded-md border border-dashed p-6 text-center text-sm text-muted-foreground">暂无版本</div>
          ) : (
            props.versions.map((version) => (
              <div key={version.id} className="rounded-md border bg-card p-3">
                <div className="text-sm font-medium">Revision {version.revision}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {formatDate(version.createdAt)} {formatTime(version.createdAt)}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-3 w-full"
                  onClick={() => props.onRestore(version.id)}
                  disabled={props.restoringId === version.id}
                >
                  {props.restoringId === version.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                  恢复
                </Button>
              </div>
            ))
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
