import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Loader2, Lock, Copy, ExternalLink } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { ErrorNotice } from '@/components/shared/ErrorNotice'
import { Markdown } from '@/components/shared/Markdown'
import { QrCode } from '@/components/shared/QrCode'
import { isApiError } from '@/api/client'
import * as shareApi from '@/api/shareLinks'
import { formatDate } from '@/lib/utils'
import { isRecord, readString, readStringFrom } from '@/lib/record'

function copyText(text: string): Promise<boolean> {
  try {
    return navigator.clipboard.writeText(text).then(() => true).catch(() => false)
  } catch {
    return Promise.resolve(false)
  }
}

export default function SharePage() {
  const { token = '' } = useParams()
  const shareUrl = useMemo(() => {
    const t = String(token || '').trim()
    if (!t) return ''
    return `${window.location.origin}/share/${t}`
  }, [token])

  const [meta, setMeta] = useState<shareApi.ShareLinkMeta | null>(null)
  const [password, setPassword] = useState('')
  const [content, setContent] = useState<shareApi.SharedContent | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isFetchingContent, setIsFetchingContent] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [copied, setCopied] = useState(false)

  const tokenValue = String(token || '').trim()

  const loadContent = async (pw: string) => {
    setIsFetchingContent(true)
    setError(null)
    try {
      const data = await shareApi.fetchSharedContent(tokenValue, pw)
      setContent(data)
    } catch (e) {
      setError(e)
    } finally {
      setIsFetchingContent(false)
    }
  }

  useEffect(() => {
    let active = true
    const run = async () => {
      setIsLoading(true)
      setError(null)
      setMeta(null)
      setContent(null)
      try {
        const m = await shareApi.getShareMeta(tokenValue)
        if (!active) return
        setMeta(m)
        if (!m.has_password) {
          await loadContent('')
        }
      } catch (e) {
        if (!active) return
        setError(e)
      } finally {
        if (active) setIsLoading(false)
      }
    }
    if (tokenValue) run()
    else setIsLoading(false)
    return () => {
      active = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tokenValue])

  const handleCopyLink = async () => {
    if (!shareUrl) return
    const ok = await copyText(shareUrl)
    setCopied(ok)
    if (ok) window.setTimeout(() => setCopied(false), 1200)
  }

  if (!tokenValue) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background text-foreground p-6">
        <Card className="w-full max-w-lg p-6">
          <div className="text-lg font-semibold">分享链接无效</div>
          <div className="text-sm text-muted-foreground mt-2">缺少 token。</div>
        </Card>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground p-6">
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-xl font-semibold tracking-tight">只读分享</div>
            <div className="text-sm text-muted-foreground break-all">{shareUrl}</div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button type="button" variant="outline" size="sm" onClick={handleCopyLink}>
              <Copy className="h-4 w-4 mr-2" />
              {copied ? '已复制' : '复制链接'}
            </Button>
            <Button type="button" variant="outline" size="sm" asChild>
              <a href={shareUrl} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4 mr-2" />
                新窗口
              </a>
            </Button>
          </div>
        </div>

        <div className="flex flex-col md:flex-row gap-4">
          <Card className="p-4 md:w-[240px] shrink-0">
            <div className="text-sm font-medium mb-3">二维码</div>
            <div className="flex items-center justify-center">
              <QrCode text={shareUrl} size={180} className="rounded-md border" />
            </div>
            {meta?.expires_at && (
              <div className="mt-3 text-xs text-muted-foreground">
                过期时间：{formatDate(meta.expires_at)}
              </div>
            )}
          </Card>

          <Card className="p-4 flex-1 min-w-0">
            {isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                加载中…
              </div>
            )}

            {Boolean(error) && <ErrorNotice error={error} />}

            {!isLoading && meta?.has_password && !content && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Lock className="h-4 w-4" />
                  需要密码
                </div>
                <div className="flex gap-2">
                  <Input
                    type="password"
                    placeholder="请输入访问密码"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="flex-1"
                  />
                  <Button
                    type="button"
                    onClick={() => loadContent(password)}
                    disabled={isFetchingContent}
                  >
                    {isFetchingContent ? <Loader2 className="h-4 w-4 animate-spin" /> : '查看'}
                  </Button>
                </div>
              </div>
            )}

            {isFetchingContent && (
              <div className="mt-4 flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在加载内容…
              </div>
            )}

            {content?.item_type === 'study_archive' && (
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <Markdown markdown={readString(content.study_archive, 'markdown')} />
              </div>
            )}

            {content?.item_type === 'paper' && (
              <div className="space-y-4">
                <div>
                  <div className="text-lg font-semibold">
                    {readStringFrom(content.paper, ['paper_name', 'name']) || '试卷'}
                  </div>
                  <div className="text-xs text-muted-foreground mt-1">
                    试卷 ID：{readStringFrom(content.paper, ['paper_id', 'id'])}
                  </div>
                </div>

                <div className="overflow-auto border rounded-md">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50">
                      <tr>
                        <th className="text-left px-3 py-2 whitespace-nowrap">题号</th>
                        <th className="text-left px-3 py-2 whitespace-nowrap">题型</th>
                        <th className="text-left px-3 py-2 whitespace-nowrap">难度</th>
                        <th className="text-left px-3 py-2 whitespace-nowrap">知识点</th>
                        <th className="text-left px-3 py-2 whitespace-nowrap">题目ID</th>
                        <th className="text-left px-3 py-2 whitespace-nowrap">来源</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(() => {
                        const rawList = isRecord(content.paper) ? content.paper.questions : undefined
                        const list = Array.isArray(rawList) ? rawList : []
                        return list.map((q, idx) => {
                          const questionId = readStringFrom(q, ['question_id', 'questionId'])
                          const order = readStringFrom(q, ['order', 'question_order']) || String(idx + 1)
                          const sourceUrl = readStringFrom(q, ['source_url', 'sourceUrl'])
                          return (
                            <tr key={questionId || idx} className="border-t">
                              <td className="px-3 py-2">{order}</td>
                              <td className="px-3 py-2">{readStringFrom(q, ['type', 'question_type'])}</td>
                              <td className="px-3 py-2">{readString(q, 'difficulty')}</td>
                              <td className="px-3 py-2">{readStringFrom(q, ['knowledge_point', 'knowledgePoint'])}</td>
                              <td className="px-3 py-2 font-mono">{questionId}</td>
                              <td className="px-3 py-2">
                                {sourceUrl ? (
                                  <a
                                    href={sourceUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-primary underline underline-offset-4"
                                  >
                                    链接
                                  </a>
                                ) : (
                                  <span className="text-muted-foreground">-</span>
                                )}
                              </td>
                            </tr>
                          )
                        })
                      })()}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

            {content?.item_type === 'template' && (
              <div className="space-y-4">
                <div>
                  <div className="text-lg font-semibold">{readString(content.template, 'name') || '模板'}</div>
                  <div className="text-xs text-muted-foreground mt-1">
                    模板 ID：{readString(content.template, 'id')} · 类型：{readString(content.template, 'template_type')}
                  </div>
                </div>
                <pre className="max-h-[70vh] overflow-auto rounded-md border bg-muted/20 p-3 text-xs leading-5">
                  {JSON.stringify(isRecord(content.template) ? content.template.body ?? {} : {}, null, 2)}
                </pre>
              </div>
            )}

            {!isLoading && meta && !error && !content && !meta.has_password && (
              <div className="text-sm text-muted-foreground">暂无内容。</div>
            )}

            {!isLoading && meta && isApiError(error) && (
              <div className="mt-2 text-xs text-muted-foreground">
                requestId: <span className="font-mono">{error.requestId || ''}</span>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  )
}
