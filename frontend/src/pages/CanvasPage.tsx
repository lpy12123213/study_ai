import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Save, Loader2, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export default function CanvasPage() {
  const [isLoading, setIsLoading] = useState(true)
  const [boardName, setBoardName] = useState('未命名画布')

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsLoading(false)
    }, 1000)
    return () => clearTimeout(timer)
  }, [])

  return (
    <div className="h-full flex flex-col bg-zinc-100 dark:bg-zinc-900">
      <div className="h-12 border-b border-border bg-background/80 backdrop-blur flex items-center justify-between px-4 z-10">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" asChild>
            <Link to="/chat">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <Input
            value={boardName}
            onChange={(e) => setBoardName(e.target.value)}
            className="h-8 w-48 bg-transparent border-none focus-visible:ring-0"
          />
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            <Save className="h-4 w-4 mr-2" />
            保存
          </Button>
        </div>
      </div>

      <div className="flex-1 relative">
        {isLoading ? (
          <div className="absolute inset-0 flex items-center justify-center">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <div className="h-20 w-20 rounded-2xl bg-muted ring-1 ring-border/60 flex items-center justify-center mx-auto mb-4">
                <Plus className="h-10 w-10 text-muted-foreground" />
              </div>
              <h3 className="text-lg font-medium mb-2">学习画布</h3>
              <p className="text-muted-foreground text-sm max-w-md">
                在这里你可以自由地组织和展示题目、笔记和思维导图。
                <br />
                tldraw 画布组件将在此处加载。
              </p>
              <p className="text-xs text-muted-foreground mt-4">
                注意：需要安装 tldraw 依赖才能使用完整画布功能
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
