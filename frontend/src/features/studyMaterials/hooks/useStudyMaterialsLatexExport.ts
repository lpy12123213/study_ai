import { useMemo, useRef, useState } from 'react'
import { downloadText, fetchSSERequest } from '@/api/client'
import { formatStudyMaterialsError, extractMarkdownHref, toText } from '@/features/studyMaterials/utils'
import { normalizeSseEnvelope } from '@/lib/sse'
import type { Message } from '@/types'
import type { LatexLessonPlanOption } from '@/features/studyMaterials/types'

type LessonPlansById = Record<string, unknown>

export function useStudyMaterialsLatexExport(opts: {
  defaultSubject: string
  lessonPlansById: LessonPlansById
  conversations: Array<any>
  messagesByConversation: Record<string, Message[] | undefined>
}) {
  const { defaultSubject, lessonPlansById, conversations, messagesByConversation } = opts

  const [latexDialogOpen, setLatexDialogOpen] = useState(false)
  const [latexLessonPlanId, setLatexLessonPlanId] = useState('')
  const [latexFileName, setLatexFileName] = useState('')
  const [latexTopic, setLatexTopic] = useState('')
  const [latexSubject, setLatexSubject] = useState('')
  const [latexMarkdown, setLatexMarkdown] = useState('')
  const [latexIsConverting, setLatexIsConverting] = useState(false)
  const [latexError, setLatexError] = useState<string | null>(null)
  const latexSourceAbortRef = useRef<AbortController | null>(null)
  const [latexIsLoadingSource, setLatexIsLoadingSource] = useState(false)
  const latexConvertAbortRef = useRef<AbortController | null>(null)
  const [latexProgressPercent, setLatexProgressPercent] = useState(0)
  const [latexProgressStage, setLatexProgressStage] = useState('')
  const [latexTexUrl, setLatexTexUrl] = useState('')
  const [latexTexFilename, setLatexTexFilename] = useState('')
  const [latexTexText, setLatexTexText] = useState('')
  const [latexNotice, setLatexNotice] = useState<string | null>(null)

  const latexLessonPlanOptions = useMemo((): LatexLessonPlanOption[] => {
    const options: LatexLessonPlanOption[] = []

    for (const p of Object.values(lessonPlansById || {})) {
      const id = toText((p as any)?.id).trim()
      const mdUrl = toText((p as any)?.mdUrl).trim()
      if (!id || !mdUrl) continue

      options.push({
        id,
        sourceType: 'lesson_plan',
        title: toText((p as any)?.title) || undefined,
        subject: toText((p as any)?.subject) || undefined,
        grade: toText((p as any)?.grade) || undefined,
        createdAt: toText((p as any)?.createdAt) || undefined,
        mdUrl,
        mdFilename: toText((p as any)?.mdFilename) || undefined,
      })
    }

    const seen = new Set(options.map((o) => o.id))
    for (const c of conversations || []) {
      if (!c || (c.type !== 'lesson_plan' && c.type !== 'study_materials')) continue
      const cid = toText(c.id).trim()
      if (!cid) continue
      if (seen.has(cid)) continue

      const list = messagesByConversation?.[cid] ?? []
      let mdUrl = ''
      for (let i = list.length - 1; i >= 0; i--) {
        const href = extractMarkdownHref(toText(list[i]?.content))
        if (href) {
          mdUrl = href
          break
        }
      }
      if (!mdUrl) continue

      options.push({
        id: cid,
        sourceType: c.type === 'study_materials' ? 'study_materials' : 'lesson_plan',
        title: toText(c.title) || undefined,
        createdAt: toText(c.createdAt) || undefined,
        mdUrl,
      })
      seen.add(cid)
    }

    options.sort((a, b) => {
      const ta = toText(a.createdAt)
      const tb = toText(b.createdAt)
      if (!ta && !tb) return 0
      if (!ta) return 1
      if (!tb) return -1
      return tb.localeCompare(ta)
    })

    return options
  }, [lessonPlansById, conversations, messagesByConversation])

  const latexLessonPlanOptionById = useMemo(() => {
    const out: Record<string, LatexLessonPlanOption> = {}
    for (const opt of latexLessonPlanOptions) out[opt.id] = opt
    return out
  }, [latexLessonPlanOptions])

  const openLatexDialog = () => {
    if (!latexSubject.trim()) setLatexSubject(defaultSubject || '')
    setLatexDialogOpen(true)
  }

  const handlePickLessonPlanMarkdown = async (planId: string) => {
    const resolvedId = toText(planId).trim()
    setLatexLessonPlanId(resolvedId)

    if (latexSourceAbortRef.current) {
      latexSourceAbortRef.current.abort()
      latexSourceAbortRef.current = null
    }

    setLatexError(null)
    setLatexNotice(null)
    setLatexProgressPercent(0)
    setLatexProgressStage('')
    setLatexTexUrl('')
    setLatexTexFilename('')
    setLatexTexText('')
    setLatexMarkdown('')
    setLatexFileName('')

    if (!resolvedId) return

    const plan = latexLessonPlanOptionById[resolvedId]
    const mdUrl = toText(plan?.mdUrl)
    if (!mdUrl) {
      setLatexError('未找到可导出的文档，请先成功生成内容后再试。')
      return
    }

    const topic = toText(plan?.title)
    if (topic) setLatexTopic(topic)
    const subj = toText(plan?.subject)
    if (subj) setLatexSubject(subj)
    setLatexFileName(toText(plan?.mdFilename))

    const controller = new AbortController()
    latexSourceAbortRef.current = controller
    setLatexIsLoadingSource(true)
    try {
      const text = await downloadText(mdUrl, { signal: controller.signal })
      setLatexMarkdown(text)
    } catch (err: any) {
      const msg = toText(err?.message) || '加载文档失败'
      setLatexError(formatStudyMaterialsError(msg))
    } finally {
      setLatexIsLoadingSource(false)
      if (latexSourceAbortRef.current === controller) {
        latexSourceAbortRef.current = null
      }
    }
  }

  const clearLatexLessonPlanSelection = () => {
    void handlePickLessonPlanMarkdown('')
  }

  const handleConvertToLatex = async () => {
    const md = (latexMarkdown || '').trim()
    if (!md || latexIsConverting || latexIsLoadingSource) return

    if (latexConvertAbortRef.current) {
      latexConvertAbortRef.current.abort()
      latexConvertAbortRef.current = null
    }
    const controller = new AbortController()
    latexConvertAbortRef.current = controller

    setLatexIsConverting(true)
    setLatexError(null)
    setLatexNotice(null)
    setLatexProgressPercent(0)
    setLatexProgressStage('')
    setLatexTexUrl('')
    setLatexTexFilename('')
    setLatexTexText('')

    try {
      let donePayload: any = null

      await fetchSSERequest(
        '/study-materials/convert-markdown-to-latex/stream',
        {
          method: 'POST',
          body: {
            markdown: md,
            topic: latexTopic.trim(),
            subject: latexSubject.trim(),
          },
          signal: controller.signal,
        },
        (data) => {
          const env = normalizeSseEnvelope(data)
          const kind = env.type
          const payload = env.data as any

          if (kind === 'status') {
            const text = toText(payload?.content)
            if (text) setLatexProgressStage(text)
            return
          }

          if (kind === 'progress') {
            const percentRaw = payload?.percent
            const percent =
              typeof percentRaw === 'number' ? percentRaw : typeof percentRaw === 'string' ? Number(percentRaw) : NaN
            if (Number.isFinite(percent)) {
              setLatexProgressPercent(Math.max(0, Math.min(100, percent as number)))
            }
            const stage = toText(payload?.stage)
            if (stage) setLatexProgressStage(stage)
            return
          }

          if (kind === 'done') {
            donePayload = payload
            return
          }

          if (kind === 'error') {
            const msg = formatStudyMaterialsError(toText(payload?.message) || '转换失败')
            setLatexError(msg)
            return
          }
        },
        (err) => {
          const msg = formatStudyMaterialsError(toText((err as any)?.message) || '转换失败')
          setLatexError(msg)
        }
      )

      const texUrl = toText(donePayload?.tex_url)
      const filename = toText(donePayload?.filename)

      if (!texUrl) {
        throw new Error('转换失败')
      }

      setLatexTexUrl(texUrl)
      setLatexTexFilename(filename)

      setLatexProgressPercent(100)
      setLatexProgressStage('加载排版稿…')

      const texText = await downloadText(texUrl, { signal: controller.signal })
      setLatexTexText(texText)
    } catch (err: any) {
      const msg = toText(err?.message) || '转换失败'
      setLatexError(formatStudyMaterialsError(msg))
    } finally {
      setLatexIsConverting(false)
      if (latexConvertAbortRef.current === controller) {
        latexConvertAbortRef.current = null
      }
    }
  }

  const handleCopyLatex = async () => {
    const tex = (latexTexText || '').trim()
    if (!tex) return
    try {
      await navigator.clipboard.writeText(tex)
      setLatexNotice('已复制')
      window.setTimeout(() => setLatexNotice(null), 1600)
    } catch (err) {
      const msg = err instanceof Error ? err.message : '复制失败'
      setLatexError(msg)
    }
  }

  return {
    latexDialogOpen,
    setLatexDialogOpen,
    latexLessonPlanId,
    setLatexLessonPlanId,
    latexFileName,
    setLatexFileName,
    latexTopic,
    setLatexTopic,
    latexSubject,
    setLatexSubject,
    latexMarkdown,
    setLatexMarkdown,
    latexIsConverting,
    setLatexIsConverting,
    latexError,
    setLatexError,
    latexIsLoadingSource,
    setLatexIsLoadingSource,
    latexProgressPercent,
    setLatexProgressPercent,
    latexProgressStage,
    setLatexProgressStage,
    latexTexUrl,
    setLatexTexUrl,
    latexTexFilename,
    setLatexTexFilename,
    latexTexText,
    setLatexTexText,
    latexNotice,
    setLatexNotice,
    latexLessonPlanOptions,
    latexLessonPlanOptionById,
    openLatexDialog,
    handlePickLessonPlanMarkdown,
    clearLatexLessonPlanSelection,
    handleConvertToLatex,
    handleCopyLatex,
  }
}
