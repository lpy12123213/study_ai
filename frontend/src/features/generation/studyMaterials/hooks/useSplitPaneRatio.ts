import { useCallback, useRef, useState } from 'react'

/**
 * Manages the resizable split-pane ratio for the study-materials view.
 * `handleDrag` adjusts the left-panel width ratio, clamped to [0.2, 0.65].
 */
export function useSplitPaneRatio(initialRatio = 0.38) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [leftRatio, setLeftRatio] = useState(initialRatio)

  const handleDrag = useCallback((deltaX: number) => {
    if (!containerRef.current) return
    const totalWidth = containerRef.current.offsetWidth
    if (totalWidth <= 0) return
    setLeftRatio((prev) => {
      const next = prev + deltaX / totalWidth
      return Math.max(0.2, Math.min(0.65, next))
    })
  }, [])

  return { containerRef, leftRatio, setLeftRatio, handleDrag }
}
