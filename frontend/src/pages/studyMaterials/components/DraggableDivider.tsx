import { useCallback, useEffect, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { GripVertical } from 'lucide-react'

export function DraggableDivider({ onDrag }: { onDrag: (deltaX: number) => void }) {
  const [dragging, setDragging] = useState(false)
  const lastX = useRef(0)
  const onDragRef = useRef(onDrag)

  useEffect(() => {
    onDragRef.current = onDrag
  }, [onDrag])

  useEffect(() => {
    if (!dragging) return

    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMouseMove = (ev: MouseEvent) => {
      const dx = ev.clientX - lastX.current
      lastX.current = ev.clientX
      onDragRef.current(dx)
    }
    const onMouseUp = () => {
      setDragging(false)
    }

    document.addEventListener('mousemove', onMouseMove)
    document.addEventListener('mouseup', onMouseUp)

    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      document.removeEventListener('mousemove', onMouseMove)
      document.removeEventListener('mouseup', onMouseUp)
    }
  }, [dragging])

  const onMouseDown = useCallback((e: ReactMouseEvent<HTMLDivElement>) => {
    e.preventDefault()
    lastX.current = e.clientX
    setDragging(true)
  }, [])

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
