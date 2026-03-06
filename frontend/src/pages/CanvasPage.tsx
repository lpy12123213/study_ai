import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Save, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

export default function CanvasPage() {
  const [boardName, setBoardName] = useState('未命名画布')

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
          <Button variant="outline" size="sm" disabled title="学习画布正在开发中，暂不支持保存">
            <Save className="h-4 w-4 mr-2" />
            保存（开发中）
          </Button>
        </div>
      </div>

      <div className="flex-1 relative">
        <div className="h-full flex items-center justify-center">
          <div className="text-center px-6">
            <div className="h-20 w-20 rounded-2xl bg-muted ring-1 ring-border/60 flex items-center justify-center mx-auto mb-4">
              <Plus className="h-10 w-10 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium mb-2">学习画布（开发中）</h3>
            <p className="text-muted-foreground text-sm max-w-md mx-auto">
              该功能正在开发中：未来会支持自由组织题目、笔记与思维导图，并提供保存/恢复。
            </p>
            <p className="text-xs text-muted-foreground mt-4">
              现在你仍可以使用「对话 / 深度解题 / 自学资料」完成主要学习流程。
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
