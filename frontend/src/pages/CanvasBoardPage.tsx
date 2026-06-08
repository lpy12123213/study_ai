import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { getCanvasBoardVersion, updateCanvasBoard, type CanvasBoard as CanvasBoardType } from '@/api/canvas'
import { BoardToolbar } from '@/features/canvas/components/BoardToolbar'
import { CanvasBoard } from '@/features/canvas/components/CanvasBoard'
import { ConflictDialog } from '@/features/canvas/components/ConflictDialog'
import { PickQuestionsPanel } from '@/features/canvas/components/PickQuestionsPanel'
import { VersionsDrawer } from '@/features/canvas/components/VersionsDrawer'
import {
  useCanvasBoard,
  useCanvasVersions,
  useCreateCanvasVersion,
  usePickCanvasQuestions,
  useUpdateCanvasBoard,
} from '@/features/canvas/hooks'
import { useCanvasStore } from '@/features/canvas/store'

export default function CanvasBoardPage() {
  const { boardId } = useParams<{ boardId: string }>()
  const boardQuery = useCanvasBoard(boardId)
  const updateBoard = useUpdateCanvasBoard(boardId)
  const versionsQuery = useCanvasVersions(boardId)
  const createVersion = useCreateCanvasVersion(boardId)
  const pickQuestions = usePickCanvasQuestions(boardId)

  const [pickOpen, setPickOpen] = useState(false)
  const [versionsOpen, setVersionsOpen] = useState(false)
  const [conflictBoard, setConflictBoard] = useState<CanvasBoardType | null>(null)
  const [restoringId, setRestoringId] = useState<number | null>(null)

  const boardState = useCanvasStore()

  useEffect(() => {
    if (!boardQuery.data) return
    const current = useCanvasStore.getState()
    if (current.boardId !== boardQuery.data.id || !current.dirty) {
      current.loadBoard(boardQuery.data)
    }
  }, [boardQuery.data])

  const saveSnapshot = async (expectedRevision = boardState.revision) => {
    const result = await updateBoard.mutateAsync({
      title: boardState.title,
      subject: boardState.subject,
      snapshot: boardState.snapshot(),
      expectedRevision,
    })
    if (result.success) {
      boardState.applySavedBoard(result.board)
    } else {
      setConflictBoard(result.serverBoard)
    }
  }

  const restoreVersion = async (versionId: number) => {
    if (!boardId) return
    setRestoringId(versionId)
    try {
      const version = await getCanvasBoardVersion(boardId, versionId)
      if (!version.snapshot) return
      const result = await updateCanvasBoard(boardId, {
        snapshot: version.snapshot,
        expectedRevision: useCanvasStore.getState().revision,
      })
      if (result.success) {
        boardState.applySavedBoard(result.board)
        setVersionsOpen(false)
      } else {
        setConflictBoard(result.serverBoard)
      }
    } finally {
      setRestoringId(null)
    }
  }

  if (boardQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (boardQuery.error || !boardQuery.data) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <div className="text-sm text-muted-foreground">看板不存在</div>
        <Button asChild variant="outline">
          <Link to="/canvas">返回列表</Link>
        </Button>
      </div>
    )
  }

  return (
    <main className="flex h-screen flex-col bg-background">
      <BoardToolbar
        title={boardState.title}
        subject={boardState.subject}
        dirty={boardState.dirty}
        saving={updateBoard.isPending}
        onTitleChange={boardState.setTitle}
        onSubjectChange={boardState.setSubject}
        onAddNote={() => boardState.addNote({ text: '' })}
        onSave={() => void saveSnapshot()}
        onOpenPick={() => setPickOpen((open) => !open)}
        onOpenVersions={() => setVersionsOpen(true)}
      />
      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1">
          <CanvasBoard
            nodes={boardState.nodes}
            onMoveNode={(nodeId, x, y) => boardState.moveNode(nodeId, { x, y })}
            onUpdateNote={boardState.updateNote}
          />
        </div>
        {pickOpen && (
          <PickQuestionsPanel
            subject={boardState.subject}
            loading={pickQuestions.isPending}
            onPick={async (input) => {
              const result = await pickQuestions.mutateAsync(input)
              return result.questions
            }}
            onAdd={(questions) => boardState.addQuestions(questions)}
          />
        )}
      </div>

      <VersionsDrawer
        open={versionsOpen}
        versions={versionsQuery.data || []}
        loading={versionsQuery.isLoading}
        creating={createVersion.isPending}
        restoringId={restoringId}
        onOpenChange={setVersionsOpen}
        onCreateVersion={() => void createVersion.mutateAsync()}
        onRestore={(versionId) => void restoreVersion(versionId)}
      />

      <ConflictDialog
        open={Boolean(conflictBoard)}
        serverBoard={conflictBoard}
        onOpenChange={(open) => {
          if (!open) setConflictBoard(null)
        }}
        onDiscardLocal={() => {
          if (conflictBoard) boardState.applyServerBoard(conflictBoard)
          setConflictBoard(null)
        }}
        onOverwrite={() => {
          const expected = conflictBoard?.revision || boardState.revision
          setConflictBoard(null)
          void saveSnapshot(expected)
        }}
      />
    </main>
  )
}
