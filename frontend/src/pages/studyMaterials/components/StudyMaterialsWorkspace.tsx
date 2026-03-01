import { AnimatePresence, motion } from 'framer-motion'
import { ChevronLeft, ChevronRight, Layers, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DraggableDivider } from '@/pages/studyMaterials/components/DraggableDivider'
import { MessageBubble } from '@/pages/studyMaterials/components/MessageBubble'
import { SubAgentPanel } from '@/pages/studyMaterials/components/SubAgentPanel'
import type { StudyMaterialsController } from '@/pages/studyMaterials/hooks/useStudyMaterialsController'

export function StudyMaterialsWorkspace({ controller }: { controller: StudyMaterialsController }) {
  const {
    scrollRef,
    leftRatio,
    showSplitPane,
    messages,
    handleMessageScroll,
    hasResumableStream,
    isGenerating,
    activeConversationId,
    activeConversation,
    resumeActiveStream,
    discardResumableStream,
    isLastExportFailure,
    startContinueIteration,
    error,
    hasSubAgentPane,
    subAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    setSubAgentCollapsed,
  } = controller

  const lastTask = activeConversation?.lastTask

  return (
    <div className="flex-1 flex overflow-hidden min-h-0 relative">
      {/* ── Left column: Main agent (chat + steps) ── */}
      <div className="flex flex-col overflow-hidden" style={{ width: showSplitPane ? `${leftRatio * 100}%` : '100%' }}>
        <div
          ref={scrollRef}
          className="flex-1 overflow-auto p-4 pb-32 overscroll-contain min-h-0"
          onScroll={handleMessageScroll}
        >
          <div className="py-6">
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

            <AnimatePresence mode="popLayout">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </AnimatePresence>

            {isGenerating && messages[messages.length - 1]?.content === '' && (
              <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="flex gap-3 mb-4">
                <div className="h-5 w-5 rounded-md bg-primary/10 flex items-center justify-center shrink-0">
                  <Loader2 className="h-3 w-3 animate-spin text-primary" />
                </div>
                <div className="text-sm text-muted-foreground pt-0.5">正在生成...</div>
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

