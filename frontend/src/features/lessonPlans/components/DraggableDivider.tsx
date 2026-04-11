import { useCallback, useRef } from 'react'
import { GripVertical } from 'lucide-react'

export function DraggableDivider({ onDrag }: { onDrag: (deltaX: number) => void }) {
  const dragging = useRef(false)
  const lastX = useRef(0)

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragging.current = true
      lastX.current = e.clientX
      document.body.style.cursor = 'col-resize'
      document.body.style.userSelect = 'none'

      const onMouseMove = (ev: MouseEvent) => {
        if (!dragging.current) return
        const dx = ev.clientX - lastX.current
        lastX.current = ev.clientX
        onDrag(dx)
      }
      const onMouseUp = () => {
        dragging.current = false
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
        document.removeEventListener('mousemove', onMouseMove)
        document.removeEventListener('mouseup', onMouseUp)
      }
      document.addEventListener('mousemove', onMouseMove)
      document.addEventListener('mouseup', onMouseUp)
    },
    [onDrag]
  )

  return (
    <div
      className="w-2 shrink-0 cursor-col-resize flex items-center justify-center group hover:bg-primary/10 transition-colors relative z-10"
      onMouseDown={onMouseDown}
      role="separator"
      aria-orientation="vertical"
      tabIndex={0}
    >
      <GripVertical className="h-5 w-5 text-muted-foreground/30 group-hover:text-primary/50 transition-colors" />
    </div>
  )
}

