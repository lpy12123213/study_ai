import { BookmarkPlus, ExternalLink, MessageSquarePlus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { cn } from '@/lib/utils'
import type { Question } from '@/types'

export interface PaperDetailQuestionsProps {
  questionsByType: Record<string, Question[]>
  activeHash: string
  onAddToWrongbook: (question: Question) => void
  onAnnotate: (questionId: string, snippet: string) => void
}

export function PaperDetailQuestions({
  questionsByType,
  activeHash,
  onAddToWrongbook,
  onAnnotate,
}: PaperDetailQuestionsProps) {
  if (Object.keys(questionsByType).length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground">
        <p>暂无题目</p>
      </div>
    )
  }

  return (
    <>
      {Object.entries(questionsByType).map(([type, questions], typeIndex) => (
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
                  activeHash === `question-${String(question.questionId)}` &&
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
                        onClick={() => onAddToWrongbook(question)}
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
                          onAnnotate(
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
                      <div className="mt-2 max-h-60 overflow-auto rounded-md bg-muted/30 border border-border/60 p-3">
                        <QuestionContent content={question.stem} className="text-sm leading-6" />
                      </div>
                    </details>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </>
  )
}
