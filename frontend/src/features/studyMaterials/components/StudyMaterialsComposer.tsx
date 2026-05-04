import { Plus, Send, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { StudyMaterialsController } from '@/features/studyMaterials/hooks/useStudyMaterialsController'
import type { TriState } from '@/features/studyMaterials/types'

type PresetValue = 'default' | 'quick' | 'standard' | 'deep' | 'research'

export function StudyMaterialsComposer({ controller }: { controller: StudyMaterialsController }) {
  const {
    showSplitPane,
    leftRatio,
    optionsOpen,
    setOptionsOpen,
    isGenerating,
    openLatexDialog,
    subject,
    setSubject,
    preset,
    setPreset,
    withDiagrams,
    setWithDiagrams,
    withQuestions,
    setWithQuestions,
    enableExtraTools,
    setEnableExtraTools,
    maxPoints,
    setMaxPoints,
    requirements,
    setRequirements,
    handleSubmit,
    handleNewConversation,
    textareaRef,
    input,
    setInput,
    handleKeyDown,
    stopGenerating,
  } = controller

  const presetValue: PresetValue = (preset as PresetValue) || 'default'

  return (
    <div
      className="absolute bottom-0 left-0 right-0 p-4 bg-gradient-to-t from-background via-background to-transparent pt-10 pointer-events-none"
      style={showSplitPane ? { width: `${leftRatio * 100}%` } : undefined}
    >
      <div className="max-w-3xl mx-auto pointer-events-auto">
        <Collapsible open={optionsOpen} onOpenChange={setOptionsOpen}>
          <div className="flex items-center justify-between gap-3 mb-2">
            <CollapsibleTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 px-2 text-xs text-muted-foreground hover:text-foreground"
                disabled={isGenerating}
              >
                {optionsOpen ? '收起选项' : '高级选项'}
              </Button>
            </CollapsibleTrigger>
            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 px-2 text-xs"
                onClick={openLatexDialog}
                disabled={isGenerating}
              >
                排版导出
              </Button>
              <div className="text-[10px] text-muted-foreground/70">未填写时使用本地默认配置</div>
            </div>
          </div>

          <CollapsibleContent>
            <div className="mb-3 rounded-2xl border border-border bg-card/80 backdrop-blur p-3 shadow-sm">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">学科（可选）</div>
                  <Input
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="例如：高中数学 / 大学物理 / 英语"
                    disabled={isGenerating}
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">生成预设</div>
                  <Select
                    value={presetValue}
                    onValueChange={(v) => {
                      const value = v as PresetValue
                      if (value === 'default') {
                        setPreset('')
                        return
                      }
                      if (value === 'quick' || value === 'standard' || value === 'deep' || value === 'research') {
                        setPreset(value)
                      }
                    }}
                    disabled={isGenerating}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="默认（平衡）" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">默认（平衡）</SelectItem>
                      <SelectItem value="quick">快速（更快更短）</SelectItem>
                      <SelectItem value="standard">标准（平衡）</SelectItem>
                      <SelectItem value="deep">深入（更深更细）</SelectItem>
                      <SelectItem value="research">研究型（更重资料）</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">示意图</div>
                  <Select
                    value={withDiagrams}
                    onValueChange={(v) => setWithDiagrams(v as TriState)}
                    disabled={isGenerating}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="默认" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">默认</SelectItem>
                      <SelectItem value="on">开启</SelectItem>
                      <SelectItem value="off">关闭</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">题库（例题/练习）</div>
                  <Select
                    value={withQuestions}
                    onValueChange={(v) => setWithQuestions(v as TriState)}
                    disabled={isGenerating}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="默认" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">默认</SelectItem>
                      <SelectItem value="on">开启</SelectItem>
                      <SelectItem value="off">关闭</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">额外资料来源（百科/问答/公开笔记）</div>
                  <Select
                    value={enableExtraTools}
                    onValueChange={(v) => setEnableExtraTools(v as TriState)}
                    disabled={isGenerating}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="默认" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="default">默认</SelectItem>
                      <SelectItem value="on">开启</SelectItem>
                      <SelectItem value="off">关闭</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-muted-foreground">知识点数量上限（1-15）</div>
                  <Input
                    type="number"
                    min={1}
                    max={15}
                    value={maxPoints}
                    onChange={(e) => setMaxPoints(e.target.value)}
                    placeholder="留空=默认"
                    disabled={isGenerating}
                  />
                </div>

                <div className="space-y-1.5 sm:col-span-2">
                  <div className="text-xs font-medium text-muted-foreground">额外要求（可选）</div>
                  <Textarea
                    value={requirements}
                    onChange={(e) => setRequirements(e.target.value)}
                    placeholder="例如：更通俗一些 / 更严谨一些 / 偏直观解释 / 偏推导证明 / 强调常见误区"
                    className="min-h-[64px] resize-none"
                    disabled={isGenerating}
                    rows={2}
                  />
                </div>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        <form onSubmit={handleSubmit} className="relative group">
          <div className="relative flex items-end gap-2 p-2 rounded-2xl border bg-background shadow-sm ring-offset-background focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 transition-all">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-9 w-9 rounded-xl text-muted-foreground hover:text-foreground shrink-0 mb-0.5"
              onClick={handleNewConversation}
              title="新建对话"
            >
              <Plus className="h-5 w-5" />
            </Button>

            <Textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="例如：函数单调性 / 二次函数最值 / 受力分析..."
              className="min-h-[44px] max-h-[200px] w-full resize-none border-0 bg-transparent py-2.5 px-0 focus-visible:ring-0 focus-visible:ring-offset-0 placeholder:text-muted-foreground/50"
              disabled={isGenerating}
              rows={1}
              style={{ height: 'auto', overflow: 'hidden' }}
              onInput={(e) => {
                const target = e.currentTarget
                target.style.height = 'auto'
                target.style.height = `${Math.min(target.scrollHeight, 200)}px`
              }}
            />

            {isGenerating ? (
              <Button
                type="button"
                size="icon"
                variant="destructive"
                className="h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all"
                onClick={stopGenerating}
                title="停止生成"
              >
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                type="submit"
                size="icon"
                className={cn(
                  'h-9 w-9 rounded-xl shrink-0 mb-0.5 transition-all',
                  input.trim() ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'
                )}
                disabled={!input.trim()}
              >
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
        </form>

        <div className="text-center mt-2 text-[10px] text-muted-foreground/50">内容由 AI 生成，仅供参考。</div>
      </div>
    </div>
  )
}

