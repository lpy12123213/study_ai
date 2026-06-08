import { motion } from 'framer-motion'
import { Textarea } from '@/components/ui/textarea'
import type { CanvasNoteNode } from '@/api/canvas'

interface NoteCardProps {
  node: CanvasNoteNode
  onMove: (x: number, y: number) => void
  onChange: (text: string) => void
}

export function NoteCard({ node, onMove, onChange }: NoteCardProps) {
  return (
    <motion.article
      drag
      dragMomentum={false}
      onDragEnd={(_event, info) => onMove(node.x + info.offset.x, node.y + info.offset.y)}
      className="absolute rounded-md border bg-amber-50 text-amber-950 shadow-sm dark:bg-amber-950/40 dark:text-amber-50"
      style={{ x: node.x, y: node.y, width: node.w, minHeight: node.h }}
    >
      <Textarea
        value={node.text}
        onChange={(event) => onChange(event.target.value)}
        placeholder="写下思路、错因或复习提醒"
        className="min-h-[150px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0"
      />
    </motion.article>
  )
}
