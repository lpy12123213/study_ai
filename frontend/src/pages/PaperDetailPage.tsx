import { useMemo } from 'react'
import { useParams, Link } from 'react-router-dom'
import {
  ArrowLeft,
  ExternalLink,
  FileText,
  Link2,
  Loader2,
  Printer,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import { usePaper, usePaperDownloadLink } from '@/hooks/usePapers'
import { formatDate } from '@/lib/utils'

export default function PaperDetailPage() {
  const { paperId } = useParams<{ paperId: string }>()
  const { data: paper, isLoading, error } = usePaper(paperId)
  const {
    mutate: loadDownloadLinks,
    data: download,
    isPending: isLoadingLinks,
  } = usePaperDownloadLink()

  const handlePrint = () => {
    window.print()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !paper) {
    return (
      <div className="flex flex-col items-center justify-center h-full">
        <FileText className="h-12 w-12 text-muted-foreground mb-4" />
        <p className="text-muted-foreground mb-4">试卷不存在或加载失败</p>
        <Button asChild variant="outline">
          <Link to="/papers">返回列表</Link>
        </Button>
      </div>
    )
  }

  const questionsByType = useMemo(() => {
    const groups: Record<string, typeof paper.questions> = {}
    for (const q of paper.questions) {
      const key = (q.type || '').trim() || '未分类'
      if (!groups[key]) groups[key] = []
      groups[key].push(q)
    }
    return groups
  }, [paper.questions])

  return (
    <div className="h-full flex flex-col">
      <div className="border-b border-border p-4 glass flex items-center justify-between print:hidden">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="icon" asChild>
            <Link to="/papers">
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div>
            <h1 className="font-semibold">{paper.name}</h1>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Badge variant="secondary">试卷 #{paper.id}</Badge>
              <span>{paper.questions.length} 道题</span>
              {!!paper.createdAt && <span>{formatDate(paper.createdAt)}</span>}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handlePrint}>
            <Printer className="h-4 w-4 mr-2" />
            打印
          </Button>
          <Button
            variant="outline"
            onClick={() => paperId && loadDownloadLinks(paperId)}
            disabled={!paperId || isLoadingLinks}
          >
            <Link2 className="h-4 w-4 mr-2" />
            获取查看链接
          </Button>
        </div>
      </div>

      <ScrollArea className="flex-1">
        <div className="max-w-4xl mx-auto p-6 print:p-0">
          <div className="text-center mb-8 print:mb-4">
            <h1 className="text-2xl font-bold mb-2">{paper.name}</h1>
            <div className="text-muted-foreground">
              题目数量：{paper.questions.length}
              {!!paper.createdAt && ` | 创建于 ${formatDate(paper.createdAt)}`}
            </div>
          </div>

          {paper.analysis && (
            <Card className="mb-8 print:border-0 print:shadow-none">
              <CardContent className="p-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="font-semibold">AI 分析</div>
                  <Badge variant="outline">
                    难度系数 {paper.analysis.difficultyScore.toFixed(2)}
                  </Badge>
                </div>
                {paper.analysis.aiComment ? (
                  <div className="mt-3 text-sm whitespace-pre-wrap text-muted-foreground">
                    {paper.analysis.aiComment}
                  </div>
                ) : (
                  <div className="mt-3 text-sm text-muted-foreground">
                    暂无 AI 评语
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {Object.keys(questionsByType).length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <p>暂无题目</p>
            </div>
          ) : (
            Object.entries(questionsByType).map(([type, questions], typeIndex) => (
              <div key={type} className="mb-8">
                <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <span className="h-6 w-6 rounded-full bg-primary text-primary-foreground text-sm flex items-center justify-center">
                    {typeIndex + 1}
                  </span>
                  {type}
                  <span className="text-sm font-normal text-muted-foreground">
                    (共 {questions.length} 题)
                  </span>
                </h2>

                <div className="space-y-4">
                  {questions.map((question, index) => (
                    <Card
                      key={`${question.questionId}-${index}`}
                      className="print:shadow-none print:border-0"
                    >
                      <CardContent className="p-4">
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-muted-foreground shrink-0">
                                {index + 1}.
                              </span>
                              <span className="font-mono text-sm truncate">
                                {question.questionId}
                              </span>
                            </div>

                            <div className="mt-2 flex flex-wrap gap-2">
                              {!!question.difficulty && (
                                <Badge variant="outline">{question.difficulty}</Badge>
                              )}
                              {!!question.knowledgePoint && (
                                <Badge variant="outline">
                                  {question.knowledgePoint}
                                </Badge>
                              )}
                            </div>
                          </div>

                          {!!question.sourceUrl ? (
                            <Button variant="outline" size="sm" asChild>
                              <a
                                href={question.sourceUrl}
                                target="_blank"
                                rel="noreferrer"
                              >
                                <ExternalLink className="h-4 w-4 mr-2" />
                                打开原题
                              </a>
                            </Button>
                          ) : (
                            <Badge variant="secondary" className="shrink-0">
                              无链接
                            </Badge>
                          )}
                        </div>
                      </CardContent>
                    </Card>
                  ))}
                </div>
              </div>
            ))
          )}

          {!!download?.success && (
            <>
              <Separator className="my-8" />
              <Card className="print:border-0 print:shadow-none">
                <CardContent className="p-4">
                  <div className="font-semibold mb-2">
                    查看链接（合规：跳转组卷网）
                  </div>

                  {!!download.instructions?.length && (
                    <ol className="list-decimal pl-5 space-y-1 text-sm text-muted-foreground">
                      {download.instructions.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ol>
                  )}

                  {!!download.questionLinks?.length ? (
                    <div className="mt-4 grid gap-2">
                      {download.questionLinks.map((url, i) => (
                        <a
                          key={`${url}-${i}`}
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-sm text-primary hover:underline break-all"
                        >
                          {i + 1}. {url}
                        </a>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 text-sm text-muted-foreground">
                      暂无链接
                    </div>
                  )}
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </ScrollArea>
    </div>
  )
}
