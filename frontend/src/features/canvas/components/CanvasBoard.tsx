import type { CanvasNode } from '@/api/canvas'
import { NoteCard } from '@/features/canvas/components/NoteCard'
import { QuestionCard } from '@/features/canvas/components/QuestionCard'

interface CanvasBoardProps {
  nodes: CanvasNode[]
  onMoveNode: (nodeId: string, x: number, y: number) => void
  onUpdateNote: (nodeId: string, text: string) => void
}

export function CanvasBoard({ nodes, onMoveNode, onUpdateNote }: CanvasBoardProps) {
  return (
    <div className="aurora-canvas-board relative h-full min-h-[720px] w-full overflow-auto">
      <div className="relative h-[1800px] w-[2400px]">
        {nodes.length === 0 && (
          <div className="aurora-canvas-empty-note absolute left-16 top-16 px-4 py-3 text-sm">
            添加便签或从右侧选题入板
          </div>
        )}
        {nodes.map((node) =>
          node.kind === 'note' ? (
            <NoteCard
              key={node.id}
              node={node}
              onMove={(x, y) => onMoveNode(node.id, x, y)}
              onChange={(text) => onUpdateNote(node.id, text)}
            />
          ) : (
            <QuestionCard key={node.id} node={node} onMove={(x, y) => onMoveNode(node.id, x, y)} />
          )
        )}
      </div>
    </div>
  )
}
