import { ArrowLeft, ClipboardCheck, Download, Link2, Loader2, Printer, Share2 } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'

export type PaperSourceMode = 'mixed' | 'zujuan' | 'local'
export type PaperExportFormat = 'markdown' | 'pdf' | 'docx'

export interface PaperDetailHeaderProps {
  paperId: string | undefined
  isExporting: boolean
  sourceMode: PaperSourceMode
  docxIncludeAnswer: boolean
  onDocxIncludeAnswerChange: (value: boolean) => void
  docxIncludeAnalysis: boolean
  onDocxIncludeAnalysisChange: (value: boolean) => void
  isLoadingLinks: boolean
  onShare: () => void
  onStartExam: () => void
  onPrint: () => void
  onExport: (format: PaperExportFormat) => void
  onLoadDownloadLinks: () => void
}

export function PaperDetailHeader({
  paperId,
  isExporting,
  sourceMode,
  docxIncludeAnswer,
  onDocxIncludeAnswerChange,
  docxIncludeAnalysis,
  onDocxIncludeAnalysisChange,
  isLoadingLinks,
  onShare,
  onStartExam,
  onPrint,
  onExport,
  onLoadDownloadLinks,
}: PaperDetailHeaderProps) {
  return (
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
        <Button variant="default" size="sm" onClick={onStartExam} disabled={!paperId}>
          <ClipboardCheck className="h-4 w-4 mr-2" />
          开始答题
        </Button>
        <Button variant="outline" size="sm" onClick={onShare} disabled={!paperId}>
          <Share2 className="h-4 w-4 mr-2" />
          分享
        </Button>
        <Button variant="outline" size="sm" onClick={onPrint}>
          <Printer className="h-4 w-4 mr-2" />
          打印
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onExport('markdown')}
          disabled={!paperId || isExporting}
        >
          {isExporting ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Download className="h-4 w-4 mr-2" />
          )}
          导出可编辑文档
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => onExport('pdf')}
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
                <Switch checked={docxIncludeAnswer} onCheckedChange={(v: boolean) => onDocxIncludeAnswerChange(Boolean(v))} />
                <div className="text-xs text-muted-foreground select-none">答案</div>
              </div>
              <div className="flex items-center gap-2">
                <Switch checked={docxIncludeAnalysis} onCheckedChange={(v: boolean) => onDocxIncludeAnalysisChange(Boolean(v))} />
                <div className="text-xs text-muted-foreground select-none">解析</div>
              </div>
            </div>
            <Button
              variant="default"
              size="sm"
              onClick={() => onExport('docx')}
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
            onClick={onLoadDownloadLinks}
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
  )
}
