import { AnimatePresence } from 'framer-motion'
import { BrainCircuit, ChevronDown, ChevronLeft, ChevronRight, FileText, Layers, Loader2, Radar } from 'lucide-react'
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
    lastTaskStatusError,
    lastFailedStage,
    lastTaskResumable,
    error,
    clearError,
    hasSubAgentPane,
    subAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    setSubAgentCollapsed,
  } = controller

  const lastTask = activeConversation?.lastTask
  const failureStagePresentation: Record<string, { label: string; actionLabel?: string }> = {
    plan: { label: '规划', actionLabel: '继续规划' },
    research: { label: '检索研究', actionLabel: '继续研究' },
    draft: { label: '起草', actionLabel: '继续起草' },
    review: { label: '审查', actionLabel: '继续审查' },
    revise: { label: '修订', actionLabel: '继续修订' },
    accept: { label: '验收', actionLabel: '继续验收' },
    search: { label: '检索' },
    aggregate: { label: '聚合' },
    write: { label: '写作' },
    export: { label: '导出' },
  }
  const failedStagePresentation = failureStagePresentation[lastFailedStage]
  const lastFailedStageLabel = failedStagePresentation?.label || ''
  const shouldVirtualize = messages.length >= 500
  const completedSubAgents = subAgentActivities.filter((activity) => activity.status === 'completed').length
  const runningSubAgents = subAgentActivities.filter((activity) => activity.status === 'running').length
  const engineStatus =
    isGenerating
      ? '运行中'
      : activeConversation?.status === 'failed'
        ? '待修复'
        : activeConversation?.status === 'completed'
          ? '已完成'
          : '待命'
  const workspaceStats = [
    { label: '对话轮次', value: `${messages.length}`, icon: FileText },
    { label: '知识点编队', value: `${completedSubAgents}/${subAgentActivities.length || 0}`, icon: BrainCircuit },
    { label: '运行状态', value: runningSubAgents > 0 ? `${runningSubAgents} 个研究中` : engineStatus, icon: Radar },
  ]
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
            <section className="aurora-materials-ops mb-5">
              <div>
                <div className="aurora-kicker">
                  <BrainCircuit className="h-3.5 w-3.5" />
                  Forge Console
                </div>
                <h2 className="mt-3 text-2xl font-semibold tracking-tight">学习材料铸造中枢</h2>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                  系统自动完成任务规划、检索聚合与成稿，并按知识点逐一深入研究，最终沉淀为可继续迭代和导出的自学资料。
                </p>
              </div>
              <div className="aurora-materials-ops-grid">
                {workspaceStats.map((item) => {
                  const Icon = item.icon
                  return (
                    <div key={item.label} className="aurora-materials-ops-stat">
                      <Icon className="h-4 w-4 text-primary" />
                      <span>{item.label}</span>
                      <strong>{item.value}</strong>
                    </div>
                  )
                })}
              </div>
            </section>
            {!!lastTask?.taskId && (
              <div className="aurora-materials-sticky sticky top-0 z-10 pb-3">
                <TaskProgressHeader taskId={lastTask.taskId} compact />
              </div>
            )}
            {hasResumableStream && !isGenerating && activeConversationId && activeConversation?.activeStream && (
              <div className="aurora-materials-notice mt-3 mb-4 rounded-xl p-3 text-sm">
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
              <div className="aurora-materials-notice mt-3 mb-4 rounded-xl p-3 text-sm" data-tone="danger">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-muted-foreground">
                    任务失败{lastFailedStageLabel ? `（上次失败阶段：${lastFailedStageLabel}）` : ''}。
                    {lastTaskResumable ? '你可以从失败阶段继续，或重新规划后续跑。' : '本次失败没有可恢复的进度，请直接重新发起生成。'}
                    {lastTaskStatusError && <div className="text-xs text-destructive mt-1">任务状态获取失败：{lastTaskStatusError}</div>}
                  </div>
                  {lastTaskResumable && (
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
                      {failedStagePresentation?.actionLabel && (
                        <Button size="sm" onClick={() => startContinueIteration('resume_failed_stage')}>
                          {failedStagePresentation.actionLabel}
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
                  )}
                </div>
              </div>
            )}

            {!isGenerating && activeConversationId && activeConversation?.status === 'completed' && lastTask?.taskId && (
              <div className="aurora-materials-notice mt-3 mb-4 rounded-xl p-3 text-sm" data-tone="success">
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
              <div className="aurora-materials-streaming flex gap-3 mb-4">
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
            className="aurora-materials-float-button absolute right-4 bottom-28 z-20 h-10 w-10 rounded-full"
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
          className="aurora-materials-sidecar flex flex-col overflow-hidden min-h-0"
          data-state={isGenerating ? 'running' : 'idle'}
          style={{ width: `${(1 - leftRatio) * 100}%` }}
        >
          <div className="px-4 py-3 border-b border-border/70 bg-background/50 backdrop-blur-sm flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-medium">
                <Layers className="h-4 w-4 text-primary" />
                知识点研究区
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
          className="aurora-materials-float-button absolute right-2 top-3 z-20 h-9 w-9 rounded-full"
          onClick={() => setSubAgentCollapsed(false)}
          title="展开研究面板"
        >
          <ChevronLeft className="h-4 w-4" />
        </Button>
      )}
    </div>
  )
}
