import { ExternalLink } from 'lucide-react'
import { motion } from 'framer-motion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { CanvasQuestionNode } from '@/api/canvas'

interface QuestionCardProps {
  node: CanvasQuestionNode
  onMove: (x: number, y: number) => void
}

export function QuestionCard({ node, onMove }: QuestionCardProps) {
  return (
    <motion.article
      drag
      dragMomentum={false}
      onDragEnd={(_event, info) => onMove(node.x + info.offset.x, node.y + info.offset.y)}
      className="absolute overflow-hidden rounded-md border bg-card shadow-sm"
      style={{ x: node.x, y: node.y, width: node.w, minHeight: node.h }}
    >
      <div className="flex items-start justify-between gap-3 border-b bg-muted/30 px-3 py-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-medium">{node.title}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {node.difficulty && <Badge variant="outline" className="h-5 text-[10px]">{node.difficulty}</Badge>}
            {node.type && <Badge variant="outline" className="h-5 text-[10px]">{node.type}</Badge>}
          </div>
        </div>
        {node.url && (
          <Button asChild size="icon" variant="ghost" className="h-7 w-7 shrink-0">
            <a href={node.url} target="_blank" rel="noreferrer" aria-label="打开原题">
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          </Button>
        )}
      </div>
      <div
        className="max-h-[260px] overflow-auto px-3 py-2 text-sm leading-6"
        dangerouslySetInnerHTML={{ __html: node.stemHtml || '<p>暂无题干</p>' }}
      />
      {node.selectReason && (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground">{node.selectReason}</div>
      )}
    </motion.article>
  )
}
