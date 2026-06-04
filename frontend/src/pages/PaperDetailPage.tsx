import { useEffect, useMemo, useState } from 'react'
import { useLocation, useNavigate, useParams, Link } from 'react-router-dom'
import { FileText, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { downloadObjectUrl } from '@/api/client'
import { usePaper, usePaperDownloadLink, usePaperExport } from '@/hooks/usePapers'
import { useStartExam } from '@/hooks/useExam'
import { formatDate } from '@/lib/utils'
import { ShareLinkDialog } from '@/components/shared/ShareLinkDialog'
import { AnnotationDialog } from '@/components/shared/AnnotationDialog'
import { PaperHeatmapPanel } from '@/features/generation/paperCompose/components/PaperHeatmapPanel'
import {
  PaperDetailHeader,
  type PaperExportFormat,
  type PaperSourceMode,
} from '@/features/workspace/papers/components/PaperDetailHeader'
import { PaperAnalysisPanel } from '@/features/workspace/papers/components/PaperAnalysisPanel'
import { PaperDetailQuestions } from '@/features/workspace/papers/components/PaperDetailQuestions'
import { PaperDownloadLinks } from '@/features/workspace/papers/components/PaperDownloadLinks'
import { StartExamDialog } from '@/features/workspace/papers/components/StartExamDialog'
import { useNotificationStore } from '@/stores/useNotificationStore'
import * as tasksApi from '@/api/tasks'
import * as wrongbookApi from '@/api/wrongbook'
import type { Question } from '@/types'

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
  const startExam = useStartExam()
  const paper = paperWithAnalysis || paperBase
  const pushToast = useNotificationStore((s) => s.pushToast)
  const [shareOpen, setShareOpen] = useState(false)
  const [annotateOpen, setAnnotateOpen] = useState(false)
  const [annotateAnchor, setAnnotateAnchor] = useState<string>('')
  const [annotateSnippet, setAnnotateSnippet] = useState<string>('')
  const [docxIncludeAnswer, setDocxIncludeAnswer] = useState(true)
  const [docxIncludeAnalysis, setDocxIncludeAnalysis] = useState(true)
  const [examOpen, setExamOpen] = useState(false)

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

  const handleStartExam = async (payload: { mode: 'timed' | 'untimed'; timeLimitMinutes: number | null }) => {
    if (!paperId) return
    const session = await startExam.mutateAsync({
      paperId: Number(paperId),
      mode: payload.mode,
      timeLimitMinutes: payload.timeLimitMinutes,
    })
    setExamOpen(false)
    navigate(`/exam/${session.sessionId}`)
  }

  const handleExport = async (format: PaperExportFormat) => {
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

  const addToWrongbook = async (question: Question) => {
    const qid = String(question.questionId || '').trim()
    if (!qid) return
    try {
      await wrongbookApi.upsertWrongQuestion({
        question_id: qid,
        subject: String(paper?.subject || '').trim(),
        knowledge_point: String(question.knowledgePoint || '').trim(),
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

  const sourceMode = useMemo<PaperSourceMode>(() => {
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

  const activeHash = String(location.hash || '').replace(/^#/, '')

  return (
    <div className="h-full flex flex-col bg-background">
      <PaperDetailHeader
        paperId={paperId}
        isExporting={isExporting}
        sourceMode={sourceMode}
        docxIncludeAnswer={docxIncludeAnswer}
        onDocxIncludeAnswerChange={setDocxIncludeAnswer}
        docxIncludeAnalysis={docxIncludeAnalysis}
        onDocxIncludeAnalysisChange={setDocxIncludeAnalysis}
        isLoadingLinks={isLoadingLinks}
        onShare={() => setShareOpen(true)}
        onStartExam={() => setExamOpen(true)}
        onPrint={handlePrint}
        onExport={handleExport}
        onLoadDownloadLinks={() => paperId && loadDownloadLinks(paperId)}
      />

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

          <PaperAnalysisPanel
            analysis={paper.analysis}
            paperId={paperId}
            isLoadingAnalysis={isLoadingAnalysis}
            analysisError={analysisError}
            onLoadAnalysis={() => loadAnalysis()}
          />

          <Separator className="my-8 print:hidden" />

          <PaperHeatmapPanel questions={paper.questions} />

          <PaperDetailQuestions
            questionsByType={questionsByType}
            activeHash={activeHash}
            onAddToWrongbook={addToWrongbook}
            onAnnotate={openAnnotate}
          />

          {!!download?.success && <PaperDownloadLinks download={download} />}
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

      <StartExamDialog
        open={examOpen}
        isPending={startExam.isPending}
        onOpenChange={setExamOpen}
        onStart={handleStartExam}
      />
    </div>
  )
}
