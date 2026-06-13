import { ArrowLeft, History, Loader2, Plus, Save, Search } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface BoardToolbarProps {
  title: string
  subject: string
  dirty: boolean
  saving: boolean
  onTitleChange: (title: string) => void
  onSubjectChange: (subject: string) => void
  onAddNote: () => void
  onSave: () => void
  onOpenPick: () => void
  onOpenVersions: () => void
}

export function BoardToolbar(props: BoardToolbarProps) {
  return (
    <header className="aurora-canvas-toolbar flex h-16 items-center justify-between gap-3 px-4">
      <div className="flex min-w-0 items-center gap-2">
        <Button asChild size="icon" variant="ghost">
          <Link to="/canvas" aria-label="返回画布列表">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <Input
          value={props.title}
          onChange={(event) => props.onTitleChange(event.target.value)}
          className="aurora-canvas-title-input h-9 w-56 border-0 bg-transparent px-2 text-base font-semibold shadow-none focus-visible:ring-1"
        />
        <Input
          value={props.subject}
          onChange={(event) => props.onSubjectChange(event.target.value)}
          placeholder="学科"
          className="aurora-canvas-subject-input h-9 w-32"
        />
        {props.dirty && <span className="aurora-canvas-dirty-pill text-xs">有未保存修改</span>}
      </div>
      <div className="flex items-center gap-2">
        <Button type="button" className="aurora-canvas-toolbar-button" variant="outline" onClick={props.onAddNote}>
          <Plus className="h-4 w-4" />
          便签
        </Button>
        <Button type="button" className="aurora-canvas-toolbar-button" variant="outline" onClick={props.onOpenPick}>
          <Search className="h-4 w-4" />
          选题
        </Button>
        <Button type="button" className="aurora-canvas-toolbar-button" variant="outline" onClick={props.onOpenVersions}>
          <History className="h-4 w-4" />
          版本
        </Button>
        <Button
          type="button"
          className="aurora-canvas-save-button"
          onClick={props.onSave}
          disabled={props.saving || !props.dirty}
        >
          {props.saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
          保存
        </Button>
      </div>
    </header>
  )
}
