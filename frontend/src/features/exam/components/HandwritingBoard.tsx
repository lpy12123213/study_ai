import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { HandwritingToolbar } from './HandwritingToolbar'

type Point = { x: number; y: number }
type Stroke = { color: string; width: number; points: Point[] }

interface HandwritingBoardProps {
  onImageFile: (file: File) => void | Promise<void>
  imageUrl?: string
}

export interface HandwritingBoardHandle {
  exportImage: () => Promise<boolean>
}

function canvasPoint(canvas: HTMLCanvasElement, event: React.PointerEvent<HTMLCanvasElement>): Point {
  const rect = canvas.getBoundingClientRect()
  return {
    x: ((event.clientX - rect.left) / rect.width) * canvas.width,
    y: ((event.clientY - rect.top) / rect.height) * canvas.height,
  }
}

function drawStrokes(canvas: HTMLCanvasElement, strokes: Stroke[]) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  for (const stroke of strokes) {
    if (stroke.points.length < 2) continue
    ctx.strokeStyle = stroke.color
    ctx.lineWidth = stroke.width
    ctx.beginPath()
    ctx.moveTo(stroke.points[0].x, stroke.points[0].y)
    for (const point of stroke.points.slice(1)) ctx.lineTo(point.x, point.y)
    ctx.stroke()
  }
}

export const HandwritingBoard = forwardRef<HandwritingBoardHandle, HandwritingBoardProps>(function HandwritingBoard(
  { onImageFile, imageUrl },
  ref
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const dirtyRef = useRef(false)
  const [strokes, setStrokes] = useState<Stroke[]>([])
  const [, setRedo] = useState<Stroke[]>([])
  const [color, setColor] = useState('#111827')
  const [width, setWidth] = useState(3)
  const [drawing, setDrawing] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (canvas) drawStrokes(canvas, strokes)
  }, [strokes])

  const exportImage = useCallback(async (): Promise<boolean> => {
    const canvas = canvasRef.current
    if (!canvas || !dirtyRef.current) return false
    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', 0.85)
    })
    if (!blob) return false
    await onImageFile(new File([blob], `handwriting-${Date.now()}.jpg`, { type: 'image/jpeg' }))
    dirtyRef.current = false
    return true
  }, [onImageFile])

  useImperativeHandle(ref, () => ({ exportImage }), [exportImage])

  const appendPoint = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const point = canvasPoint(canvas, event)
    setStrokes((prev) => {
      const copy = [...prev]
      const last = copy[copy.length - 1]
      if (!last) return copy
      copy[copy.length - 1] = { ...last, points: [...last.points, point] }
      return copy
    })
  }

  return (
    <div className="aurora-exam-card overflow-hidden rounded-md border bg-card" data-focus="true">
      <HandwritingToolbar
        color={color}
        width={width}
        onColorChange={setColor}
        onWidthChange={setWidth}
        onUndo={() => {
          dirtyRef.current = true
          setStrokes((prev) => {
            if (!prev.length) return prev
            setRedo((r) => [prev[prev.length - 1], ...r])
            return prev.slice(0, -1)
          })
        }}
        onRedo={() => {
          dirtyRef.current = true
          setRedo((prev) => {
            if (!prev.length) return prev
            setStrokes((s) => [...s, prev[0]])
            return prev.slice(1)
          })
        }}
        onClear={() => {
          dirtyRef.current = true
          setRedo(strokes)
          setStrokes([])
        }}
      />
      <canvas
        ref={canvasRef}
        width={1200}
        height={700}
        className="block h-[360px] w-full touch-none bg-white"
        onPointerDown={(event) => {
          event.currentTarget.setPointerCapture(event.pointerId)
          const point = canvasPoint(event.currentTarget, event)
          setRedo([])
          dirtyRef.current = true
          setStrokes((prev) => [...prev, { color, width, points: [point] }])
          setDrawing(true)
        }}
        onPointerMove={(event) => {
          if (drawing) appendPoint(event)
        }}
        onPointerUp={(event) => {
          event.currentTarget.releasePointerCapture(event.pointerId)
          setDrawing(false)
        }}
        onPointerCancel={() => setDrawing(false)}
      />
      <div className="flex items-center justify-between border-t p-2">
        {imageUrl ? (
          <a className="text-xs text-muted-foreground underline" href={imageUrl} target="_blank" rel="noreferrer">
            已上传手写图
          </a>
        ) : (
          <span className="text-xs text-muted-foreground">切题或提交前请保存当前手写内容</span>
        )}
        <Button type="button" size="sm" onClick={() => void exportImage()}>
          <Upload className="h-4 w-4" />
          保存手写
        </Button>
      </div>
    </div>
  )
})
