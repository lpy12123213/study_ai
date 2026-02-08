import { useState } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { TaskStep } from '@/types'

interface StepDetailProps {
  step: TaskStep
}

function JsonView({ data, label }: { data: unknown; label: string }) {
  const [copied, setCopied] = useState(false)

  const jsonString = JSON.stringify(data, null, 2)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(jsonString)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-medium text-muted-foreground">
          {label}
        </span>
        <Button
          variant="ghost"
          size="icon"
          className="h-6 w-6"
          onClick={handleCopy}
        >
          {copied ? (
            <Check className="h-3 w-3 text-foreground" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
        </Button>
      </div>
      <pre className="text-xs bg-muted/50 rounded-md p-3 overflow-x-auto max-h-48 overflow-y-auto">
        <code className="text-foreground/80">{jsonString}</code>
      </pre>
    </div>
  )
}

export function StepDetail({ step }: StepDetailProps) {
  const hasInput = step.input !== undefined
  const hasOutput = step.output !== undefined
  const hasError = step.error !== undefined

  const defaultTab = hasError ? 'error' : hasOutput ? 'output' : 'input'

  return (
    <div className="mt-3 pt-3 border-t border-border">
      {hasInput || hasOutput || hasError ? (
        <Tabs defaultValue={defaultTab}>
          <TabsList className="h-8">
            {hasInput && (
              <TabsTrigger value="input" className="text-xs">
                输入
              </TabsTrigger>
            )}
            {hasOutput && (
              <TabsTrigger value="output" className="text-xs">
                输出
              </TabsTrigger>
            )}
            {hasError && (
              <TabsTrigger value="error" className="text-xs text-destructive">
                错误
              </TabsTrigger>
            )}
          </TabsList>

          {hasInput && (
            <TabsContent value="input" className="mt-2">
              <JsonView data={step.input} label="工具输入" />
            </TabsContent>
          )}

          {hasOutput && (
            <TabsContent value="output" className="mt-2">
              <JsonView data={step.output} label="工具输出" />
            </TabsContent>
          )}

          {hasError && (
            <TabsContent value="error" className="mt-2">
              <div className="bg-destructive/10 border border-destructive/20 rounded-md p-3">
                <p className="text-sm text-destructive">{step.error}</p>
              </div>
            </TabsContent>
          )}
        </Tabs>
      ) : (
        <div className="text-xs text-muted-foreground">无详细信息</div>
      )}
    </div>
  )
}
