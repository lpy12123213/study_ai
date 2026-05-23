import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Brain, ChevronDown, ChevronUp, Loader2, Paperclip, RefreshCw, Send, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { ThinkingTree } from '@/components/deepthink/ThinkingTree'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { useDeepThink } from '@/hooks/useDeepThink'
import { useSubjects } from '@/hooks/useSubjects'
import { readNumber } from '@/lib/record'
import { cn, generateId } from '@/lib/utils'
import { DeepThinkUserBubble } from '@/features/generation/deepThink/components/DeepThinkUserBubble'
import { DeepThinkWelcomeScreen } from '@/features/generation/deepThink/components/DeepThinkWelcomeScreen'
import type { DeepThinkChatMessage } from '@/features/generation/deepThink/types'

export default function DeepThinkPage() {
  const { data: subjects } = useSubjects()
  const [subject, setSubject] = useState<string>('高中数学')
  const [imageUrl, setImageUrl] = useState<string>('')

  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<DeepThinkChatMessage[]>([])
  const [showOptions, setShowOptions] = useState(false)
  const [showTree, setShowTree] = useState(true)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [activeAssistantId, setActiveAssistantId] = useState<string | null>(null)
  const activeAssistantIdRef = useRef<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const stickToBottomRef = useRef(true)
  const [showJumpToBottom, setShowJumpToBottom] = useState(false)

  const { status, taskId, nodes, bestPath, answer, metrics, error, config, solve, cancel, reset } = useDeepThink()
  const isStreaming = status === 'searching' || status === 'answering'

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    stickToBottomRef.current = true
    setShowJumpToBottom(false)
    requestAnimationFrame(() => {
      const target = scrollRef.current
      if (!target) return
      target.scrollTop = target.scrollHeight
    })
  }, [])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distanceToBottom = el.scrollHeight - (el.scrollTop + el.clientHeight)
    const nearBottom = distanceToBottom < 120
    stickToBottomRef.current = nearBottom
    setShowJumpToBottom((prev) => (prev !== !nearBottom ? !nearBottom : prev))
  }, [])

  useEffect(() => {
    if (subjects && subjects.length > 0 && !subject) {
      setSubject(subjects[0].code)
    }
  }, [subjects, subject])

  useEffect(() => {
    const id = activeAssistantIdRef.current
    if (!id) return
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, content: answer } : m)))
  }, [answer])

  useEffect(() => {
    if (!stickToBottomRef.current) return
    const el = scrollRef.current
    if (!el) return
    requestAnimationFrame(() => {
      const target = scrollRef.current
      if (!target) return
      target.scrollTop = target.scrollHeight
    })
  }, [messages])

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null
    return nodes[selectedNodeId] || null
  }, [nodes, selectedNodeId])

  const configSummary = useMemo(() => {
    if (!config) return null
    return {
      bf: readNumber(config, 'branch_factor', 0),
      bw: readNumber(config, 'beam_width', 0),
      md: readNumber(config, 'max_depth', 0),
      th: readNumber(config, 'prune_threshold', 0),
    }
  }, [config])

  const statusLabel =
    status === 'idle'
      ? '等待输入'
      : status === 'searching'
        ? '思维树搜索中'
        : status === 'answering'
          ? '生成最终解答中'
          : status === 'done'
            ? '已完成'
            : '出错'

  const handleClear = () => {
    if (isStreaming) return
    activeAssistantIdRef.current = null
    setActiveAssistantId(null)
    setSelectedNodeId(null)
    setShowTree(true)
    setMessages([])
    reset()
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const question = input.trim()
    if (!question || isStreaming) return

    stickToBottomRef.current = true
    setShowJumpToBottom(false)

    const now = new Date().toISOString()
    const userMessage: DeepThinkChatMessage = {
      id: generateId(),
      role: 'user',
      content: question,
      createdAt: now,
      meta: {
        subject,
        imageUrl: imageUrl.trim() ? imageUrl.trim() : undefined,
      },
    }
    const assistantId = generateId()
    const assistantMessage: DeepThinkChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      createdAt: now,
    }

    activeAssistantIdRef.current = assistantId
    setActiveAssistantId(assistantId)
    setSelectedNodeId(null)
    setShowTree(true)
    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setInput('')

    solve(question, {
      subject,
      imageUrl: imageUrl.trim() ? imageUrl.trim() : undefined,
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const assistantIndicatorTone =
    status === 'error'
      ? 'bg-destructive'
      : status === 'done'
        ? 'bg-emerald-500'
        : status === 'searching' || status === 'answering'
          ? 'bg-primary'
          : 'bg-muted-foreground'

  return (
    <div className="h-full flex flex-col relative">
      {messages.length === 0 ? (
        <DeepThinkWelcomeScreen onExampleClick={(text) => setInput(text)} />
      ) : (
        <div ref={scrollRef} className="flex-1 overflow-auto p-4 pb-32" onScroll={handleScroll}>
          <div className="max-w-3xl mx-auto py-6">
            {!!taskId && status !== 'idle' && (
              <div className="sticky top-0 z-10 pb-3 bg-background/80 backdrop-blur-sm">
                <TaskProgressHeader taskId={taskId} compact />
              </div>
            )}
            <AnimatePresence mode="popLayout">
              {messages.map((message) => {
                if (message.role === 'user') {
                  return <DeepThinkUserBubble key={message.id} message={message} />
                }

                const isActive = !!activeAssistantId && message.id === activeAssistantId
                const nodeCount = metrics.totalNodes || Object.keys(nodes).length
                const showMetrics = isActive && (nodeCount > 0 || metrics.elapsed > 0 || status !== 'idle')

                return (
                  <motion.div
                    key={message.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex flex-col gap-2 mb-8 max-w-3xl w-full"
                  >
                    <div className="flex items-center gap-2 text-xs font-medium text-muted-foreground mb-1 select-none">
                      <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center">
                        <Brain className="h-3.5 w-3.5 text-primary" />
                      </div>
                      <span>深度解题</span>
                      {isActive && (
                        <Badge variant="outline" className="gap-1 ml-1">
                          <span className={cn('inline-block h-2 w-2 rounded-full', assistantIndicatorTone)} />
                          {statusLabel}
                        </Badge>
                      )}
                    </div>

                    <div className="prose prose-sm dark:prose-invert max-w-none text-foreground leading-7">
                      {message.content ? (
                        <div className="whitespace-pre-wrap">{message.content}</div>
                      ) : (
                        <div className="text-sm text-muted-foreground">
                          {isActive
                            ? status === 'searching'
                              ? '正在搜索最优解题路径...'
                              : status === 'answering'
                                ? '正在生成最终解答...'
                                : '解答会在完成后显示在这里。'
                            : '（历史消息）'}
                        </div>
                      )}
                    </div>

                    {showMetrics && (
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span className="tabular-nums">
                          深度 {metrics.currentDepth} · 节点 {nodeCount}
                          {metrics.bestScore > 0 ? ` · 最优分 ${metrics.bestScore.toFixed(1)}` : ''}
                          {metrics.elapsed > 0 ? ` · 耗时 ${metrics.elapsed.toFixed(1)}s` : ''}
                        </span>
                        {configSummary && (
                          <span className="tabular-nums text-muted-foreground/80">
                            · 分支 {String(configSummary.bf ?? '')} · Beam {String(configSummary.bw ?? '')} · 最大深度{' '}
                            {String(configSummary.md ?? '')}
                            {configSummary.th != null ? ` · 阈值 ${String(configSummary.th)}` : ''}
                          </span>
                        )}
                      </div>
                    )}

                    {isActive && (
                      <div className="mt-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-8 text-xs font-normal gap-1.5 bg-background hover:bg-muted/50"
                          onClick={() => setShowTree((v) => !v)}
                          disabled={Object.keys(nodes).length === 0 && status === 'idle'}
                        >
                          <Brain className="h-3.5 w-3.5 text-primary" />
                          {showTree ? '隐藏' : '查看'} 思维树
                          <span className="tabular-nums opacity-70">({nodeCount})</span>
                          {showTree ? (
                            <ChevronUp className="h-3 w-3 opacity-50" />
                          ) : (
                            <ChevronDown className="h-3 w-3 opacity-50" />
                          )}
                        </Button>

                        <AnimatePresence>
                          {showTree && (
                            <motion.div
                              initial={{ height: 0, opacity: 0 }}
                              animate={{ height: 'auto', opacity: 1 }}
                              exit={{ height: 0, opacity: 0 }}
                              className="mt-3 overflow-hidden rounded-lg border border-border bg-card"
                            >
                              <div className="p-4 bg-muted/30 space-y-3">
                                <div className="h-[420px] sm:h-[520px]">
                                  <ThinkingTree
                                    nodes={nodes}
                                    bestPath={bestPath}
                                    selectedNodeId={selectedNodeId}
                                    onSelectNode={setSelectedNodeId}
                                  />
                                </div>

                                <div className="rounded-lg border border-border bg-background p-3">
                                  {selectedNode ? (
                                    <div className="space-y-2">
                                      <div className="text-sm font-medium leading-6">{selectedNode.thought}</div>
                                      <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                                        {selectedNode.reasoning || '（无步骤说明）'}
                                      </div>
                                      <div className="flex flex-wrap items-center gap-2 text-xs">
                                        <Badge variant="outline">D{selectedNode.depth}</Badge>
                                        <Badge variant="secondary" className="tabular-nums">
                                          {selectedNode.score == null ? '...' : selectedNode.score.toFixed(1)}
                                        </Badge>
                                        <Badge variant="outline">{selectedNode.status}</Badge>
                                      </div>
                                      {selectedNode.evalReasoning && (
                                        <div className="text-xs text-muted-foreground whitespace-pre-wrap">
                                          评分理由：{selectedNode.evalReasoning}
                                        </div>
                                      )}
                                      {selectedNode.issues?.length > 0 && (
                                        <div className="text-xs text-muted-foreground">
                                          问题：
                                          <ul className="list-disc pl-5 mt-1 space-y-0.5">
                                            {selectedNode.issues.slice(0, 6).map((x) => (
                                              <li key={x}>{x}</li>
                                            ))}
                                          </ul>
                                        </div>
                                      )}
                                    </div>
                                  ) : (
                                    <div className="text-sm text-muted-foreground">点击思维树中的节点查看详情。</div>
                                  )}
                                </div>
                              </div>
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                    )}
                  </motion.div>
                )
              })}
            </AnimatePresence>

            {isStreaming && activeAssistantId && messages[messages.length - 1]?.id === activeAssistantId && messages[messages.length - 1]?.content === '' && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3 mb-4 max-w-3xl">
                <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                  <Loader2 className="h-3 w-3 animate-spin text-primary" />
                </div>
                <div className="text-sm text-muted-foreground pt-0.5">正在思考...</div>
              </motion.div>
            )}

            {error && (
              <div className="bg-destructive/10 border border-destructive/20 rounded-lg p-4 mb-4 text-sm text-destructive flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-destructive shrink-0" />
                {error}
              </div>
            )}
          </div>
        </div>
      )}

      <div className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10">
        <div className="max-w-3xl mx-auto">
          <AnimatePresence>
            {showOptions && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="overflow-hidden rounded-2xl border bg-background/80 backdrop-blur mb-2"
              >
                <div className="p-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">学科</div>
                    <Select
                      value={subject}
                      onValueChange={(v) => {
                        if (isStreaming) return
                        setSubject(v)
                      }}
                    >
                      <SelectTrigger className="h-9" disabled={isStreaming}>
                        <SelectValue placeholder="选择学科" />
                      </SelectTrigger>
                      <SelectContent>
                        {(subjects || [])
                          .filter((s) => (s.code || '').trim().length > 0)
                          .map((s) => (
                            <SelectItem key={s.id} value={s.code}>
                              {s.name}
                            </SelectItem>
                          ))}
                        {!subjects?.length && <SelectItem value="高中数学">高中数学</SelectItem>}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="sm:col-span-2">
                    <div className="text-xs text-muted-foreground mb-1">题目图片 URL（可选）</div>
                    <Input
                      value={imageUrl}
                      onChange={(e) => setImageUrl(e.target.value)}
                      placeholder="https://...（可留空）"
                      className="h-9"
                      disabled={isStreaming}
                    />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          <form onSubmit={handleSubmit} className="relative group">
            <div className="relative flex items-end gap-2 p-2 rounded-2xl border bg-background shadow-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 transition-all">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground shrink-0 mb-0.5"
                onClick={() => setShowOptions((v) => !v)}
                disabled={isStreaming}
                title="学科 / 题图"
              >
                <Paperclip className="h-5 w-5" />
              </Button>

              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground shrink-0 mb-0.5"
                onClick={handleClear}
                disabled={isStreaming || messages.length === 0}
                title="清空对话"
              >
                <RefreshCw className="h-5 w-5" />
              </Button>

              <Textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="输入题目..."
                className="min-h-[44px] max-h-[200px] w-full resize-none border-0 bg-transparent py-2.5 px-0 focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50"
                disabled={isStreaming}
                rows={1}
                style={{ height: 'auto', overflow: 'hidden' }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement
                  target.style.height = 'auto'
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`
                }}
              />

              {isStreaming ? (
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  className="h-9 w-9 rounded-xl shrink-0 mb-0.5"
                  onClick={() => cancel('user_cancelled')}
                  title="停止"
                >
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button
                  type="submit"
                  size="icon"
                  className={cn(
                    'h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all',
                    input.trim() ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                  )}
                  disabled={!input.trim()}
                >
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
          </form>

          <div className="text-center mt-2 text-[10px] text-muted-foreground/50">
            AI 生成的内容可能不准确，请核实重要信息。
          </div>
        </div>
      </div>

      {messages.length > 0 && showJumpToBottom && (
        <div className="absolute bottom-28 right-4">
          <Button type="button" variant="secondary" size="sm" className="shadow-md" onClick={scrollToBottom}>
            回到底部
            <ChevronDown className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )}
    </div>
  )
}
