import { AnimatePresence } from 'framer-motion'
import { ChevronDown, ChevronLeft, ChevronRight, Layers, Loader2 } from 'lucide-react'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { TaskProgressHeader } from '@/components/task/TaskProgressHeader'
import { Button } from '@/components/ui/button'
import { useVirtualMessages } from '@/hooks/useVirtualMessages'
import { DraggableDivider } from '@/features/generation/studyMaterials/components/DraggableDivider'
import { MessageBubble } from '@/features/generation/studyMaterials/components/MessageBubble'
import { SubAgentPanel } from '@/features/generation/studyMaterials/components/SubAgentPanel'
import type { StudyMaterialsController } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsController'

export function StudyMaterialsWorkspace({ controller }: { controller: StudyMaterialsController }) {
  const {
    scrollRef,
    leftRatio,
    showSplitPane,
    messages,
    handleMessageScroll,
    isNearBottom,
    scrollToBottom,
    hasResumableStream,
    isGenerating,
    activeConversationId,
    activeConversation,
    resumeActiveStream,
    discardResumableStream,
    isLastExportFailure,
    startContinueIteration,
    lastTaskStatus,
    lastTaskStatusError,
    error,
    clearError,
    hasSubAgentPane,
    subAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    setSubAgentCollapsed,
  } = controller

  const lastTask = activeConversation?.lastTask
  const lastFailedStage = lastTaskStatus?.last_failed_stage || ''
  const lastFailedStageLabel =
    lastFailedStage === 'search'
      ? '检索'
      : lastFailedStage === 'aggregate'
        ? '聚合'
        : lastFailedStage === 'write'
          ? '写作'
          : lastFailedStage === 'export'
            ? '导出'
            : ''
  const shouldVirtualize = messages.length >= 500
  const virtual = useVirtualMessages({
    enabled: shouldVirtualize,
    messages,
    containerRef: scrollRef,
    estimatePx: 220,
    overscan: 12,
  })

  return (
    <div className="flex-1 flex overflow-hidden min-h-0 relative">
      {/* ── Left column: Main agent (chat + steps) ── */}
      <div className="flex flex-col overflow-hidden relative" style={{ width: showSplitPane ? `${leftRatio * 100}%` : '100%' }}>
        <div
          ref={scrollRef}
          className="flex-1 overflow-auto p-4 pb-32 overscroll-contain min-h-0"
          onScroll={handleMessageScroll}
        >
          <div className="py-6">
            {!!lastTask?.taskId && (
              <div className="sticky top-0 z-10 pb-3 bg-background/80 backdrop-blur-sm">
                <TaskProgressHeader taskId={lastTask.taskId} compact />
              </div>
            )}
            {hasResumableStream && !isGenerating && activeConversationId && activeConversation?.activeStream && (
              <div className="mt-3 mb-4 rounded-xl border border-border bg-card p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-muted-foreground">
                    检测到未完成的生成任务，可继续接收输出（支持刷新恢复）。
                  </div>
                  <div className="flex items-center gap-2">
                    <Button size="sm" onClick={resumeActiveStream}>
                      继续
                    </Button>
                    <Button size="sm" variant="ghost" onClick={discardResumableStream}>
                      放弃
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {!isGenerating && activeConversationId && activeConversation?.status === 'failed' && lastTask?.taskId && (
              <div className="mt-3 mb-4 rounded-xl border border-border bg-card p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-muted-foreground">
                    任务失败{lastFailedStageLabel ? `（上次失败阶段：${lastFailedStageLabel}）` : ''}。你可以从失败阶段继续，或重新规划后续跑。
                    {lastTaskStatusError && <div className="text-xs text-destructive mt-1">任务状态获取失败：{lastTaskStatusError}</div>}
                  </div>
                  <div className="flex items-center gap-2">
                    {lastFailedStage === 'search' && (
                      <Button size="sm" onClick={() => startContinueIteration('retry_search')}>
                        继续检索
                      </Button>
                    )}
                    {(lastFailedStage === 'aggregate' || lastFailedStage === 'write') && (
                      <Button size="sm" onClick={() => startContinueIteration('resume_failed_stage')}>
                        继续写作
                      </Button>
                    )}
                    {lastFailedStage === 'export' && (
                      <>
                        <Button size="sm" variant="secondary" onClick={() => startContinueIteration('fix_export')}>
                          修复导出
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => startContinueIteration('skip_export')}>
                          跳过导出
                        </Button>
                      </>
                    )}
                    <Button size="sm" variant="outline" onClick={() => startContinueIteration('replan_from_failure')}>
                      重新规划
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {!isGenerating && activeConversationId && activeConversation?.status === 'completed' && lastTask?.taskId && (
              <div className="mt-3 mb-4 rounded-xl border border-border bg-card p-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-muted-foreground">
                    任务已完成。你可以继续迭代优化（会触发新一轮生成并更新下载链接）。
                  </div>
                  <div className="flex items-center gap-2">
                    {isLastExportFailure && (
                      <>
                        <Button size="sm" variant="secondary" onClick={() => startContinueIteration('fix_export')}>
                          修复导出
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => startContinueIteration('skip_export')}>
                          跳过导出
                        </Button>
                      </>
                    )}
                    <Button size="sm" onClick={() => startContinueIteration('improve')}>
                      继续迭代优化
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => startContinueIteration('deepen_research')}>
                      加深检索
                    </Button>
                  </div>
                </div>
              </div>
            )}

            {shouldVirtualize ? (
              <div ref={virtual.listRef} className="relative" style={{ height: virtual.totalHeight }}>
                {messages.slice(virtual.range.start, virtual.range.end).map((m, i) => {
                  const index = virtual.range.start + i
                  const mid = String(m.id)
                  const top = virtual.offsets[index] ?? 0
                  return (
                    <div
                      key={m.id}
                      ref={virtual.getMeasureRef(mid)}
                      className="absolute left-0 right-0 flow-root"
                      style={{ transform: `translateY(${top}px)` }}
                    >
                      <MessageBubble message={m} disableMotion={true} />
                    </div>
                  )
                })}
              </div>
            ) : (
              <AnimatePresence mode="popLayout">
                {messages.map((m) => (
                  <MessageBubble key={m.id} message={m} disableMotion={false} />
                ))}
              </AnimatePresence>
            )}

            {isGenerating && messages[messages.length - 1]?.content === '' && (
              <div className="flex gap-3 mb-4">
                <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                  <Loader2 className="h-3 w-3 animate-spin text-primary" />
                </div>
                <div className="text-sm text-muted-foreground pt-0.5">正在生成...</div>
              </div>
            )}

            {Boolean(error) && (
              <ErrorNotice
                error={error}
                title="生成失败"
                onRetry={hasResumableStream && !isGenerating ? resumeActiveStream : undefined}
                onClose={clearError}
              />
            )}
          </div>
        </div>

        {!isNearBottom && messages.length > 0 && (
          <Button
            type="button"
            size="icon"
            variant="secondary"
            className="absolute right-4 bottom-28 z-20 h-10 w-10 rounded-full shadow"
            onClick={scrollToBottom}
            aria-label="回到底部"
          >
            <ChevronDown className="h-4 w-4" />
          </Button>
        )}
      </div>

      {/* ── Draggable divider ── */}
      {showSplitPane && <DraggableDivider onDrag={controller.handleDrag} />}

      {/* ── Right column: SubAgent panel ── */}
      {showSplitPane && (
        <div
          className="flex flex-col overflow-hidden border-l border-border bg-muted/20 min-h-0"
          style={{ width: `${(1 - leftRatio) * 100}%` }}
        >
          <div className="px-4 py-3 border-b border-border bg-background/50 backdrop-blur-sm flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium">
                <Layers className="h-4 w-4 text-primary" />
                SubAgent 工作区
              </div>
              <div className="text-xs text-muted-foreground mt-0.5">逐知识点深入研究，为资料提供素材</div>
            </div>
            <Button
              type="button"
              size="icon"
              variant="ghost"
              className="h-8 w-8 shrink-0"
              onClick={() => setSubAgentCollapsed(true)}
              title="收起"
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
          <SubAgentPanel activities={subAgentActivities} activeTab={activeSubAgentTab} onTabChange={setActiveSubAgentTab} />
        </div>
      )}

      {!showSplitPane && hasSubAgentPane && (
        <Button
          type="button"
          size="icon"
          variant="secondary"
          className="absolute right-2 top-3 z-20 h-9 w-9 rounded-full shadow"
          onClick={() => setSubAgentCollapsed(false)}
          title="展开 SubAgent"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
      )}
    </div>
  )
}
