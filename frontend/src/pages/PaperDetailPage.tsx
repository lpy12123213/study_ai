import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams, Link } from 'react-router-dom'
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
  Printer,
  BarChart3,
  Download,
  Share2,
  MessageSquarePlus,
  BookmarkPlus,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Switch } from '@/components/ui/switch'
import { downloadObjectUrl } from '@/api/client'
import { usePaper, usePaperDownloadLink, usePaperExport } from '@/hooks/usePapers'
import { cn, formatDate } from '@/lib/utils'
import { ShareLinkDialog } from '@/components/shared/ShareLinkDialog'
import { AnnotationDialog } from '@/components/shared/AnnotationDialog'
import { useToastStore } from '@/stores/useToastStore'
import * as tasksApi from '@/api/tasks'
import * as wrongbookApi from '@/api/wrongbook'

export default function PaperDetailPage() {
  const { paperId } = useParams<{ paperId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { data: paperBase, isLoading, error } = usePaper(paperId)
  const {
    data: paperWithAnalysis,
    refetch: loadAnalysis,
    isFetching: isLoadingAnalysis,
    error: analysisError,
  } = usePaper(paperId, { includeAnalysis: true, enabled: false })
  const {
    mutate: loadDownloadLinks,
    data: download,
    isPending: isLoadingLinks,
  } = usePaperDownloadLink()
  const { mutateAsync: exportPaper, isPending: isExporting } = usePaperExport()
  const paper = paperWithAnalysis || paperBase
  const pushToast = useToastStore((s) => s.pushToast)
  const [shareOpen, setShareOpen] = useState(false)
  const [annotateOpen, setAnnotateOpen] = useState(false)
  const [annotateAnchor, setAnnotateAnchor] = useState<string>('')
  const [annotateSnippet, setAnnotateSnippet] = useState<string>('')
  const [docxIncludeAnswer, setDocxIncludeAnswer] = useState(true)
  const [docxIncludeAnalysis, setDocxIncludeAnalysis] = useState(true)

  useEffect(() => {
    const anchor = String(location.hash || '').replace(/^#/, '').trim()
    if (!anchor) return
    if (!paper) return
    window.setTimeout(() => {
      const el = document.getElementById(anchor)
      el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 50)
  }, [location.hash, paper])

  const handlePrint = () => {
    window.print()
  }

  const handleExport = async (format: 'markdown' | 'pdf' | 'docx') => {
    if (!paperId) return
    try {
      const includeAnswer = format === 'docx' ? docxIncludeAnswer : false
      const includeAnalysis = format === 'docx' ? docxIncludeAnalysis : false
      const { taskId } = await tasksApi.exportPaperTask(paperId, {
        format,
        includeStem: true,
        includeAnswer,
        includeAnalysis,
      })
      if (taskId) {
        pushToast({
          id: `export-${taskId}`,
          title: '已加入导出队列',
          taskId,
          status: 'running',
        })
        navigate('/exports')
        return
      }

      // Fallback: legacy export (should be rare).
      const res = await exportPaper({
        id: paperId,
        req: { format, includeStem: true, includeAnswer, includeAnalysis },
      })
      const url = res.url || res.pdfUrl || res.texUrl
      if (url) {
        const { objectUrl, revoke } = await downloadObjectUrl(url)
        const win = window.open(objectUrl, '_blank', 'noopener,noreferrer')
        if (!win) {
          const a = document.createElement('a')
          a.href = objectUrl
          a.download = ''
          a.click()
        }
        window.setTimeout(revoke, 60_000)
      }
    } catch {
      // Ignore: UI already shows export state; user can retry.
    }
  }

  const openAnnotate = (questionId: string, snippet: string) => {
    setAnnotateAnchor(`question-${questionId}`)
    setAnnotateSnippet(snippet)
    setAnnotateOpen(true)
  }

  const addToWrongbook = async (question: any) => {
    const qid = String(question?.questionId || question?.question_id || '').trim()
    if (!qid) return
    try {
      await wrongbookApi.upsertWrongQuestion({
        question_id: qid,
        subject: String(paper?.subject || '').trim(),
        knowledge_point: String(question?.knowledgePoint || question?.knowledge_point || '').trim(),
        mastery: 0,
        note: '',
        source_ref: {
          type: 'paper',
          paper_id: Number(paper?.id || paperId || 0) || undefined,
        },
      })
      pushToast({ id: `wrongbook-${qid}`, title: '已加入错题本' })
    } catch {
      pushToast({ id: `wrongbook-failed-${qid}`, title: '加入错题本失败' })
    }
  }

  const questionsByType = useMemo(() => {
    if (!paper) return {}
    const groups: Record<string, typeof paper.questions> = {}
    for (const q of paper.questions) {
      const key = (q.type || '').trim() || '未分类'
      if (!groups[key]) groups[key] = []
      groups[key].push(q)
    }
    return groups
  }, [paper])

  const sourceMode = useMemo(() => {
    const ids = (paper?.questions || []).map((q) => String(q.questionId || '').trim()).filter(Boolean)
    const hasDigits = ids.some((x) => /^\d+$/.test(x))
    const hasNonDigits = ids.some((x) => x && !/^\d+$/.test(x))
    if (hasDigits && hasNonDigits) return 'mixed'
    return hasDigits ? 'zujuan' : 'local'
  }, [paper])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !paper) {
    return (
      <div className="flex flex-col items-center justify-center h-full p-6 text-center">
        <div className="h-16 w-16 bg-muted rounded-full flex items-center justify-center mb-4">
          <FileText className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium mb-2">试卷不存在</h3>
        <p className="text-muted-foreground mb-6">加载失败或已被删除</p>
        <Button asChild variant="outline">
          <Link to="/papers">返回列表</Link>
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col bg-background">
      <div className="border-b border-border p-4 flex items-center justify-between sticky top-0 bg-background/80 backdrop-blur-sm z-10 print:hidden">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild className="rounded-full">
            <Link to="/papers">
              <ArrowLeft className="h-5 w-5" />
            </Link>
          </Button>
          <div className="hidden sm:block">
            <h1 className="font-semibold text-sm">试卷详情</h1>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setShareOpen(true)} disabled={!paperId}>
            <Share2 className="h-4 w-4 mr-2" />
            分享
          </Button>
          <Button variant="outline" size="sm" onClick={handlePrint}>
            <Printer className="h-4 w-4 mr-2" />
            打印
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleExport('markdown')}
            disabled={!paperId || isExporting}
          >
            {isExporting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Download className="h-4 w-4 mr-2" />
            )}
            导出 Markdown
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleExport('pdf')}
            disabled={!paperId || isExporting}
          >
            {isExporting ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Download className="h-4 w-4 mr-2" />
            )}
            导出 PDF
          </Button>

          {sourceMode === 'local' && (
            <>
              <div className="flex items-center gap-2 rounded-lg border px-3 py-2">
                <div className="flex items-center gap-2">
                  <Switch checked={docxIncludeAnswer} onCheckedChange={(v: boolean) => setDocxIncludeAnswer(Boolean(v))} />
                  <div className="text-xs text-muted-foreground select-none">答案</div>
                </div>
                <div className="flex items-center gap-2">
                  <Switch checked={docxIncludeAnalysis} onCheckedChange={(v: boolean) => setDocxIncludeAnalysis(Boolean(v))} />
                  <div className="text-xs text-muted-foreground select-none">解析</div>
                </div>
              </div>
              <Button
                variant="default"
                size="sm"
                onClick={() => handleExport('docx')}
                disabled={!paperId || isExporting}
              >
                {isExporting ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Download className="h-4 w-4 mr-2" />
                )}
                导出 DOCX
              </Button>
            </>
          )}

          {sourceMode === 'zujuan' && (
            <Button
              variant="default"
              size="sm"
              onClick={() => paperId && loadDownloadLinks(paperId)}
              disabled={!paperId || isLoadingLinks}
            >
              {isLoadingLinks ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <Link2 className="h-4 w-4 mr-2" />
              )}
              导出到组卷网
            </Button>
          )}
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto p-8 print:p-0">
          <div className="text-center mb-8 print:mb-6">
            <div className="inline-flex items-center justify-center h-16 w-16 rounded-2xl bg-primary/10 text-primary mb-6 print:hidden">
              <FileText className="h-8 w-8" />
            </div>
            <h1 className="text-3xl font-bold tracking-tight mb-4 text-foreground">{paper.name}</h1>

            <div className="flex flex-wrap items-center justify-center gap-3 text-sm text-muted-foreground">
              <Badge variant="secondary" className="px-3 py-1 text-sm font-normal">试卷 #{paper.id}</Badge>
              <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
              <span>{paper.questions.length} 道题</span>
              <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
              <span>{formatDate(paper.createdAt)}</span>
            </div>
          </div>

          {paper.analysis ? (
            <div className="mb-8 p-4 rounded-xl bg-muted/30 border border-border/50 print:hidden">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2 font-semibold">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  AI 智能分析
                </div>
                <Badge variant="outline" className="bg-background">
                  难度系数 {Number.isFinite(paper.analysis.difficultyScore) ? paper.analysis.difficultyScore.toFixed(2) : '--'}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground leading-6">
                {paper.analysis.aiComment || "暂无详细评语"}
              </p>
            </div>
          ) : (
            <div className="mb-8 p-4 rounded-xl bg-muted/30 border border-border/50 print:hidden">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2 font-semibold">
                    <BarChart3 className="h-4 w-4 text-primary" />
                    AI 智能分析
                  </div>
                  <p className="mt-2 text-sm text-muted-foreground">
                    默认不请求外部分析服务。需要时再手动加载，并复用缓存结果。
                  </p>
                  {analysisError && (
                    <p className="mt-2 text-sm text-destructive">
                      加载失败，请稍后重试。
                    </p>
                  )}
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => loadAnalysis()}
                  disabled={!paperId || isLoadingAnalysis}
                >
                  {isLoadingAnalysis ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <BarChart3 className="h-4 w-4 mr-2" />
                  )}
                  加载分析
                </Button>
              </div>
            </div>
          )}

          <Separator className="my-8 print:hidden" />

          {Object.keys(questionsByType).length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <p>暂无题目</p>
            </div>
          ) : (
            Object.entries(questionsByType).map(([type, questions], typeIndex) => (
              <div key={type} className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-3">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground text-sm font-medium">
                    {typeIndex + 1}
                  </span>
                  {type}
                  <span className="text-sm font-normal text-muted-foreground">
                    (共 {questions.length} 题)
                  </span>
                </h2>

                <div className="space-y-4 pl-2 border-l-2 border-border/50 ml-3.5">
                  {questions.map((question, index) => (
                    <div
                      key={`${question.questionId}-${index}`}
                      id={`question-${String(question.questionId)}`}
                      className={cn(
                        'group relative pl-6 py-2 rounded-lg',
                        String(location.hash || '').replace(/^#/, '') === `question-${String(question.questionId)}` &&
                          'ring-2 ring-primary/20 ring-offset-2 ring-offset-background'
                      )}
                    >
                      <div className="absolute left-[-5px] top-5 h-2.5 w-2.5 rounded-full border-2 border-background bg-muted-foreground/30 group-hover:bg-primary transition-colors" />

                      <div className="rounded-lg border border-border bg-card p-4 transition-all hover:shadow-sm">
                        <div className="flex items-start justify-between gap-4">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="font-mono text-xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                #{question.questionId}
                              </span>
                              <div className="flex gap-1.5">
                                {!!question.difficulty && (
                                  <Badge variant="outline" className="text-[10px] h-5">{question.difficulty}</Badge>
                                )}
                                {!!question.knowledgePoint && (
                                  <Badge variant="outline" className="text-[10px] h-5">
                                    {question.knowledgePoint}
                                  </Badge>
                                )}
                              </div>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-8"
                              onClick={() => addToWrongbook(question)}
                              aria-label="加入错题本"
                            >
                              <BookmarkPlus className="h-3.5 w-3.5 mr-1.5" />
                              错题本
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              className="h-8"
                              onClick={() =>
                                openAnnotate(
                                  String(question.questionId),
                                  `题目 #${String(question.questionId)} ${String(question.knowledgePoint || '')}`.trim()
                                )
                              }
                              aria-label="添加批注"
                            >
                              <MessageSquarePlus className="h-3.5 w-3.5 mr-1.5" />
                              批注
                            </Button>
                            {question.sourceUrl ? (
                              <Button variant="ghost" size="sm" asChild className="h-8">
                                <a href={question.sourceUrl} target="_blank" rel="noopener noreferrer">
                                  <ExternalLink className="h-3.5 w-3.5 mr-1.5" />
                                  原题
                                </a>
                              </Button>
                            ) : (
                              <span className="text-[10px] text-muted-foreground/50 select-none">无链接</span>
                            )}
                          </div>
                        </div>

                        {!!question.stem && (
                          <details className="mt-3">
                            <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground select-none">
                              查看题干
                            </summary>
                            <div className="mt-2 max-h-60 overflow-auto rounded-md bg-muted/30 border border-border/60 p-3 text-sm whitespace-pre-wrap leading-6">
                              {question.stem}
                            </div>
                          </details>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}

          {!!download?.success && (
            <>
              <Separator className="my-8" />
              <Card className="print:border-0 print:shadow-none bg-muted/30">
                <CardContent className="p-6">
                  <div className="font-semibold mb-4 flex items-center gap-2">
                    <Link2 className="h-4 w-4" />
                    查看链接
                  </div>

                  {!!download.instructions?.length && (
                    <ol className="list-decimal pl-5 space-y-1 text-sm text-muted-foreground mb-4">
                      {download.instructions.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ol>
                  )}

                  {download.questionLinks?.length ? (
                    <div className="grid gap-2">
                      {download.questionLinks.map((url, i) => (
                        <a
                          key={`${url}-${i}`}
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm text-primary hover:underline break-all block p-2 rounded hover:bg-background transition-colors"
                        >
                          {i + 1}. {url}
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      暂无链接
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </ScrollArea>

      <ShareLinkDialog
        open={shareOpen}
        onOpenChange={setShareOpen}
        itemType="paper"
        itemId={String(paperId || paper?.id || '')}
        title={paper?.name}
      />

      <AnnotationDialog
        open={annotateOpen}
        onOpenChange={setAnnotateOpen}
        itemType="paper"
        itemId={String(paperId || paper?.id || '')}
        anchor={annotateAnchor}
        snippet={annotateSnippet}
      />
    </div>
  )
}
