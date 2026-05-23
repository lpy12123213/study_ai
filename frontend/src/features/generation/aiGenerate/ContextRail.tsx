import { useMemo, useState } from 'react'
import { ChevronDown, Library, Network, RotateCcw, Rows3 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { AiGenerateKnowledgeNode, AiGenerateSessionMode } from '@/features/generation/aiGenerate/types'

interface ContextRailProps {
  subject: string
  mode: AiGenerateSessionMode
  sessionStatus?: string
  gradeId: string
  textbookVersionId: string
  grades: Array<{ id: number; name: string }>
  textbookVersions: Array<{ id: string; name: string }>
  knowledgeTree: AiGenerateKnowledgeNode[]
  isKnowledgeLoading: boolean
  knowledgeError?: string
  selectedKnowledgeIds: string[]
  selectedKnowledgeLabels: string[]
  libraryTotal: number
  onGradeChange: (value: string) => void
  onTextbookVersionChange: (value: string) => void
  onToggleKnowledgePoint: (node: AiGenerateKnowledgeNode) => void
  onClearKnowledgePoints: () => void
}

interface KnowledgeTreeNodeItemProps {
  node: AiGenerateKnowledgeNode
  depth: number
  selectedIds: Set<string>
  expandedMap: Record<string, boolean>
  onToggleExpand: (id: string) => void
  onToggleKnowledgePoint: (node: AiGenerateKnowledgeNode) => void
}

function isSelectableNode(node: AiGenerateKnowledgeNode): boolean {
  if (node.selectable === false) return false
  if (node.type === 'knowledge_point') return true
  return !Array.isArray(node.children) || node.children.length === 0
}

function KnowledgeTreeNodeItem(props: KnowledgeTreeNodeItemProps) {
  const { node, depth, selectedIds, expandedMap, onToggleExpand, onToggleKnowledgePoint } = props
  const children = Array.isArray(node.children) ? node.children : []
  const expandable = children.length > 0
  const expanded = expandable ? expandedMap[node.id] ?? depth < 1 : false
  const selectable = isSelectableNode(node)
  const selected = selectedIds.has(node.id)

  return (
    <div>
      <div
        className="flex items-center gap-2 rounded-2xl px-2 py-2 transition-colors hover:bg-accent/50"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        {expandable ? (
          <button
            type="button"
            className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-border/70 bg-background/85 text-muted-foreground"
            onClick={() => onToggleExpand(node.id)}
            aria-label={expanded ? `折叠${node.label}` : `展开${node.label}`}
          >
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded ? '' : '-rotate-90'}`} />
          </button>
        ) : (
          <div className="h-6 w-6" />
        )}

        <button
          type="button"
          className={`flex min-w-0 flex-1 items-center gap-3 rounded-2xl px-2 py-1.5 text-left ${
            selected ? 'bg-amber-100/70 text-amber-900 dark:bg-amber-900/25 dark:text-amber-100' : 'bg-transparent'
          }`}
          onClick={() => {
            if (selectable) onToggleKnowledgePoint(node)
            else if (expandable) onToggleExpand(node.id)
          }}
        >
          <input
            type="checkbox"
            className="h-4 w-4 rounded border-border"
            checked={selected}
            readOnly
            disabled={!selectable}
            aria-label={node.label}
          />
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium">{node.label}</div>
            <div className="text-xs text-muted-foreground">{node.type === 'chapter' ? '章节' : '知识点'}</div>
          </div>
        </button>
      </div>

      {expandable && expanded ? (
        <div className="mt-1 space-y-1">
          {children.map((child) => (
            <KnowledgeTreeNodeItem
              key={child.id}
              node={child}
              depth={depth + 1}
              selectedIds={selectedIds}
              expandedMap={expandedMap}
              onToggleExpand={onToggleExpand}
              onToggleKnowledgePoint={onToggleKnowledgePoint}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

export function ContextRail(props: ContextRailProps) {
  const {
    subject,
    mode,
    sessionStatus,
    gradeId,
    textbookVersionId,
    grades,
    textbookVersions,
    knowledgeTree,
    isKnowledgeLoading,
    knowledgeError,
    selectedKnowledgeIds,
    selectedKnowledgeLabels,
    libraryTotal,
    onGradeChange,
    onTextbookVersionChange,
    onToggleKnowledgePoint,
    onClearKnowledgePoints,
  } = props

  const [expandedMap, setExpandedMap] = useState<Record<string, boolean>>({})
  const selectedIds = useMemo(() => new Set(selectedKnowledgeIds), [selectedKnowledgeIds])

  return (
    <Card className="rounded-[32px] border-border/70 bg-[linear-gradient(180deg,rgba(255,255,255,0.96),rgba(246,241,231,0.92))] shadow-[0_20px_50px_rgba(29,33,44,0.08)] dark:bg-[linear-gradient(180deg,rgba(26,28,42,0.92),rgba(18,20,30,0.92))] dark:shadow-[0_20px_70px_rgba(0,0,0,0.55)]">
      <CardHeader className="border-b border-border/60 pb-4">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-200">
            <Network className="h-5 w-5" />
          </div>
          <div className="min-w-0">
            <CardTitle className="text-lg">知识点树</CardTitle>
            <div className="text-sm text-muted-foreground">按章节折叠、多选叶子节点，并把选择继续带入当前会话。</div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 p-4 lg:p-6">
        <div className="flex flex-wrap items-center gap-2 rounded-[22px] border border-border/70 bg-background/80 px-4 py-3 text-sm">
          <span className="flex items-center gap-1.5 font-medium"><Rows3 className="h-3.5 w-3.5" />{subject || '未选择学科'}</span>
          <span className="text-border">·</span>
          <Badge variant="outline" className="rounded-full">{mode === 'infinite' ? '无限模式' : '标准模式'}</Badge>
          {sessionStatus && <Badge variant="outline" className="rounded-full">{sessionStatus}</Badge>}
          <span className="text-border">·</span>
          <span className="flex items-center gap-1.5 text-muted-foreground"><Library className="h-3.5 w-3.5" />AI 题库 <span className="font-semibold text-foreground">{libraryTotal}</span></span>
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="space-y-2">
            <label htmlFor="ai-generate-grade" className="text-sm font-medium">
              年级
            </label>
            <Select value={gradeId || '__all__'} onValueChange={(value) => onGradeChange(value === '__all__' ? '' : value)}>
              <SelectTrigger id="ai-generate-grade" aria-label="年级" className="rounded-2xl">
                <SelectValue placeholder="全部年级" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">全部年级</SelectItem>
                {grades.map((item) => (
                  <SelectItem key={String(item.id)} value={String(item.id)}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <label htmlFor="ai-generate-textbook" className="text-sm font-medium">
              教材版本
            </label>
            <Select
              value={textbookVersionId || '__all__'}
              onValueChange={(value) => onTextbookVersionChange(value === '__all__' ? '' : value)}
            >
              <SelectTrigger id="ai-generate-textbook" aria-label="教材版本" className="rounded-2xl">
                <SelectValue placeholder="全部教材版本" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">全部教材版本</SelectItem>
                {textbookVersions.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <div className="rounded-[24px] border border-border/70 bg-background/80 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm font-medium">已选知识点</div>
              <div className="mt-1 text-sm text-muted-foreground">支持多选，生成请求会把这些节点写入同一会话。</div>
            </div>
            <Button type="button" variant="outline" size="sm" className="rounded-full" onClick={onClearKnowledgePoints}>
              <RotateCcw className="h-3.5 w-3.5" />
              快速清空
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {selectedKnowledgeLabels.length > 0 ? (
              selectedKnowledgeLabels.map((label) => (
                <Badge key={label} variant="outline" className="rounded-full">
                  {label}
                </Badge>
              ))
            ) : (
              <div className="text-sm text-muted-foreground">尚未选择知识点。</div>
            )}
          </div>
        </div>

        <div className="rounded-[24px] border border-border/70 bg-background/80 p-3">
          <div className="mb-3 flex items-center justify-between gap-3 px-2">
            <div>
              <div className="text-sm font-medium">教材树</div>
              <div className="mt-1 text-sm text-muted-foreground">视觉结构参考组卷网页面，按章展开并只选择知识点叶子。</div>
            </div>
            <Badge variant="outline" className="rounded-full">
              已选 {selectedKnowledgeIds.length}
            </Badge>
          </div>

          <ScrollArea className="h-[460px] pr-2">
            {knowledgeError ? (
              <div className="rounded-[18px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                {knowledgeError}
              </div>
            ) : isKnowledgeLoading ? (
              <div className="px-3 py-10 text-center text-sm text-muted-foreground">知识点树加载中...</div>
            ) : knowledgeTree.length === 0 ? (
              <div className="px-3 py-10 text-center text-sm text-muted-foreground">当前筛选条件下暂无知识点树数据。</div>
            ) : (
              <div className="space-y-1">
                {knowledgeTree.map((node) => (
                  <KnowledgeTreeNodeItem
                    key={node.id}
                    node={node}
                    depth={0}
                    selectedIds={selectedIds}
                    expandedMap={expandedMap}
                    onToggleExpand={(id) =>
                      setExpandedMap((prev) => ({
                        ...prev,
                        [id]: !(prev[id] ?? true),
                      }))
                    }
                    onToggleKnowledgePoint={onToggleKnowledgePoint}
                  />
                ))}
              </div>
            )}
          </ScrollArea>
        </div>
      </CardContent>
    </Card>
  )
}
