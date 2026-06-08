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
    <div className="relative h-full min-h-[720px] w-full overflow-auto bg-[linear-gradient(to_right,hsl(var(--border))_1px,transparent_1px),linear-gradient(to_bottom,hsl(var(--border))_1px,transparent_1px)] bg-[size:32px_32px]">
      <div className="relative h-[1800px] w-[2400px]">
        {nodes.length === 0 && (
          <div className="absolute left-16 top-16 rounded-md border border-dashed bg-background/90 px-4 py-3 text-sm text-muted-foreground">
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
