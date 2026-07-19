import { useEffect, useMemo, useRef, useState } from 'react'
import { BrainCircuit, CheckCircle2, Lightbulb, Save } from 'lucide-react'

import { saveQuestionLibraryPracticeState } from '@/api/questionLibrary'
import type {
  IntuitionPacket,
  IntuitionPracticeAttempt,
  IntuitionPracticeStage,
  IntuitionPracticeStageName,
} from '@/api/questionLibrary'
import { QuestionContent } from '@/components/shared/QuestionContent'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

const STAGE_LABELS: Record<IntuitionPracticeStageName, string> = {
  perception: '第一感觉',
  model_externalization: '说出脑中模型',
  minimal_check: '最小验证',
  transfer: '换个表面再试',
  appreciation: '解法品鉴',
}

const KIND_LABELS: Record<IntuitionPracticeStage['kind'], string> = {
  prediction: '先猜后证',
  representation: '换种表示',
  invariant: '寻找不变量',
  boundary: '试探边界',
  counterexample: '寻找反例',
  solution_comparison: '比较解法',
}

interface IntuitionPracticePanelProps {
  packet: IntuitionPacket
  practiceState?: IntuitionPracticeAttempt
  sessionId?: string
  questionId: string
  onRevealReference: () => void
}

function initialResponses(packet: IntuitionPacket, practiceState?: IntuitionPracticeAttempt): Record<string, string> {
  const values: Record<string, string> = {}
  for (const stage of packet.stages) {
    values[stage.stage] = String(practiceState?.stage_responses?.[stage.stage]?.initial_response || '')
  }
  if (practiceState?.first_guess && !String(values.perception || '').trim()) {
    values.perception = practiceState.first_guess
  }
  if (
    practiceState?.phase &&
    practiceState.final_response &&
    !String(values[practiceState.phase] || '').trim()
  ) {
    values[practiceState.phase] = practiceState.final_response
  }
  return values
}

function initialRevisedResponses(
  packet: IntuitionPacket,
  practiceState?: IntuitionPracticeAttempt
): Record<string, string> {
  const values = Object.fromEntries(
    packet.stages
      .map((stage) => [stage.stage, practiceState?.stage_responses?.[stage.stage]?.final_response || ''] as const)
      .filter(([, value]) => value)
  )
  if (
    practiceState?.phase &&
    practiceState.final_response &&
    !String(values[practiceState.phase] || '').trim()
  ) {
    values[practiceState.phase] = practiceState.final_response
  }
  return values
}

function initialRevealedStages(packet: IntuitionPacket, practiceState?: IntuitionPracticeAttempt): Set<string> {
  return new Set(
    packet.stages
      .filter((stage) => {
        const saved = practiceState?.stage_responses?.[stage.stage]
        return Boolean(saved?.final_response) || Number(saved?.hint_level || 0) > 0
      })
      .map((stage) => stage.stage)
  )
}

export function IntuitionPracticePanel(props: IntuitionPracticePanelProps) {
  const { packet, practiceState, sessionId, questionId, onRevealReference } = props
  const [responses, setResponses] = useState<Record<string, string>>(() => initialResponses(packet, practiceState))
  const [revisedResponses, setRevisedResponses] = useState<Record<string, string>>(
    () => initialRevisedResponses(packet, practiceState)
  )
  const [revealedStages, setRevealedStages] = useState<Set<string>>(
    () => initialRevealedStages(packet, practiceState)
  )
  const [confidence, setConfidence] = useState(
    Math.max(0, Math.min(100, Number(practiceState?.confidence ?? 50)))
  )
  const [hintLevel, setHintLevel] = useState(Math.max(0, Math.min(4, Number(practiceState?.hint_level ?? 0))))
  const [reflection, setReflection] = useState(String(practiceState?.reflection || ''))
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'failed'>('idle')
  const restoreSignature = JSON.stringify({ packet, practiceState })
  const lastRestoreSignatureRef = useRef(restoreSignature)

  useEffect(() => {
    if (lastRestoreSignatureRef.current === restoreSignature) return
    lastRestoreSignatureRef.current = restoreSignature
    setResponses(initialResponses(packet, practiceState))
    setRevisedResponses(initialRevisedResponses(packet, practiceState))
    setRevealedStages(initialRevealedStages(packet, practiceState))
    setConfidence(Math.max(0, Math.min(100, Number(practiceState?.confidence ?? 50))))
    setHintLevel(Math.max(0, Math.min(4, Number(practiceState?.hint_level ?? 0))))
    setReflection(String(practiceState?.reflection || ''))
    setSaveStatus('idle')
  }, [packet, practiceState, restoreSignature])

  const allAttempted = useMemo(
    () => packet.stages.length > 0 && packet.stages.every((stage) => String(responses[stage.stage] || '').trim()),
    [packet.stages, responses]
  )

  const save = async (payload: Partial<IntuitionPracticeAttempt>): Promise<boolean> => {
    if (!sessionId) return true
    setSaveStatus('saving')
    try {
      await saveQuestionLibraryPracticeState(sessionId, questionId, payload)
      setSaveStatus('saved')
      return true
    } catch {
      setSaveStatus('failed')
      return false
    }
  }

  const firstGuess = () => String(responses.perception || practiceState?.first_guess || '').trim()

  const allStageResponses = () => Object.fromEntries(
    packet.stages.map((stage) => [
      stage.stage,
      {
        initial_response: String(responses[stage.stage] || '').trim(),
        final_response: String(revisedResponses[stage.stage] || responses[stage.stage] || '').trim(),
        confidence,
        hint_level: revealedStages.has(stage.stage)
          ? Math.max(1, Number(practiceState?.stage_responses?.[stage.stage]?.hint_level || 0))
          : 0,
      },
    ])
  ) as NonNullable<IntuitionPracticeAttempt['stage_responses']>

  const revealStage = (stage: IntuitionPracticeStage) => {
    const response = String(responses[stage.stage] || '').trim()
    if (!response) return
    const stageHintLevel = stage.hint
      ? Math.max(1, Number(practiceState?.stage_responses?.[stage.stage]?.hint_level || 0))
      : 0
    const nextHintLevel = Math.max(hintLevel, stageHintLevel)
    setHintLevel(nextHintLevel)
    setRevealedStages((prev) => new Set([...prev, stage.stage]))
    setRevisedResponses((prev) => ({ ...prev, [stage.stage]: prev[stage.stage] || response }))
    void save({
      phase: stage.stage,
      first_guess: firstGuess(),
      final_response: response,
      confidence,
      hint_level: nextHintLevel,
      stage_responses: {
        [stage.stage]: {
          initial_response: response,
          final_response: response,
          confidence,
          hint_level: stageHintLevel,
        },
      },
      transfer_correct: practiceState?.transfer_correct ?? null,
      reflection,
    })
  }

  const saveRevision = (stage: IntuitionPracticeStage) => {
    const finalResponse = String(revisedResponses[stage.stage] || responses[stage.stage] || '').trim()
    void save({
      phase: stage.stage,
      first_guess: firstGuess(),
      final_response: finalResponse,
      confidence,
      hint_level: hintLevel,
      stage_responses: {
        [stage.stage]: {
          initial_response: String(responses[stage.stage] || '').trim(),
          final_response: finalResponse,
          confidence,
          hint_level: revealedStages.has(stage.stage)
            ? Math.max(1, Number(practiceState?.stage_responses?.[stage.stage]?.hint_level || 0))
            : 0,
        },
      },
      transfer_correct: practiceState?.transfer_correct ?? null,
      reflection,
    })
  }

  const completePractice = async () => {
    const lastStage = packet.stages[packet.stages.length - 1]
    const phase = lastStage?.stage || practiceState?.phase || 'transfer'
    const finalResponse = String(revisedResponses[phase] || responses[phase] || '').trim()
    const saved = await save({
      phase,
      first_guess: firstGuess(),
      final_response: finalResponse,
      confidence,
      hint_level: hintLevel,
      transfer_correct: practiceState?.transfer_correct ?? null,
      reflection: reflection.trim(),
      stage_responses: allStageResponses(),
      completed: true,
    })
    if (saved) onRevealReference()
  }

  return (
    <section
      aria-label="直觉练习包"
      className="rounded-[24px] border border-amber-200/80 bg-amber-50/45 p-4 shadow-sm dark:border-amber-800/55 dark:bg-amber-950/20"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <BrainCircuit className="h-4 w-4 text-amber-700 dark:text-amber-300" />
            <h3 className="text-sm font-semibold">直觉校准练习包</h3>
            <Badge variant="outline" className="rounded-full">{packet.atom.concept}</Badge>
          </div>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            脑内动作：{packet.atom.mental_action || '先形成第一感觉，再用证据修正。'}
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          {saveStatus === 'saving' ? '正在保存…' : null}
          {saveStatus === 'saved' ? '关键进度已保存' : null}
          {saveStatus === 'failed' ? '保存失败，当前页面仍保留作答' : null}
          {saveStatus === 'idle' ? (sessionId ? '关键进度会保存到当前会话' : '当前为本地练习') : null}
        </div>
      </div>

      {packet.curriculum_alignment ? (
        <div className="mt-3 rounded-2xl border border-border/60 bg-background/65 px-3 py-2 text-xs leading-5 text-muted-foreground">
          {packet.curriculum_alignment.knowledge_points.join('、') || '当前知识点'} · {packet.curriculum_alignment.scope_note}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-border/60 bg-background/70 px-3 py-2">
        <label htmlFor={`intuition-confidence-${questionId}`} className="text-xs font-medium">
          第一感觉把握：{confidence}%
        </label>
        <input
          id={`intuition-confidence-${questionId}`}
          aria-label="第一感觉把握"
          type="range"
          min="0"
          max="100"
          step="10"
          value={confidence}
          onChange={(event) => setConfidence(Number(event.target.value))}
          className="min-w-[160px] flex-1 accent-amber-600"
        />
      </div>

      <div className="mt-4 space-y-3">
        {packet.stages.map((stage, index) => {
          const revealed = revealedStages.has(stage.stage)
          const response = responses[stage.stage] || ''
          return (
            <div key={`${stage.stage}-${index}`} className="rounded-[20px] border border-border/65 bg-background/78 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary" className="rounded-full">{index + 1}</Badge>
                <div className="text-sm font-semibold">{STAGE_LABELS[stage.stage]}</div>
                <Badge variant="outline" className="rounded-full text-[11px]">{KIND_LABELS[stage.kind]}</Badge>
              </div>
              <QuestionContent content={stage.prompt} className="mt-3 text-sm leading-7 text-foreground/90" />
              <Textarea
                aria-label={`${STAGE_LABELS[stage.stage]}作答`}
                value={response}
                onChange={(event) => setResponses((prev) => ({ ...prev, [stage.stage]: event.target.value }))}
                placeholder="先写下第一反应和一句理由；不必一开始就追求完整证明。"
                className="mt-3 min-h-20 rounded-2xl bg-background/85"
              />
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="rounded-full"
                  disabled={!response.trim()}
                  onClick={() => revealStage(stage)}
                >
                  <Lightbulb className="h-3.5 w-3.5" />
                  {revealed ? '反馈已展开' : '提交本步并查看反馈'}
                </Button>
                {!response.trim() ? <span className="text-xs text-muted-foreground">先留下自己的判断，反馈才会展开。</span> : null}
              </div>

              {revealed ? (
                <div className="mt-3 space-y-3 rounded-2xl border border-amber-200/70 bg-amber-50/55 p-3 dark:border-amber-800/50 dark:bg-amber-950/25">
                  {stage.hint ? <div className="text-sm leading-6"><span className="font-medium">提示：</span>{stage.hint}</div> : null}
                  {stage.expected_answer ? (
                    <div className="text-sm leading-6">
                      <div className="font-medium">参考判断</div>
                      <QuestionContent content={stage.expected_answer} className="mt-1" />
                    </div>
                  ) : null}
                  {stage.feedback ? <div className="text-sm leading-6"><span className="font-medium">校准：</span>{stage.feedback}</div> : null}
                  <Textarea
                    aria-label={`${STAGE_LABELS[stage.stage]}校准后作答`}
                    value={revisedResponses[stage.stage] || ''}
                    onChange={(event) => setRevisedResponses((prev) => ({ ...prev, [stage.stage]: event.target.value }))}
                    placeholder="看过反馈后，用自己的话修正答案。"
                    className="min-h-20 rounded-2xl bg-background/85"
                  />
                  <Button type="button" variant="ghost" size="sm" className="rounded-full" onClick={() => saveRevision(stage)}>
                    <Save className="h-3.5 w-3.5" />
                    保存本步修正
                  </Button>
                </div>
              ) : null}
            </div>
          )
        })}
      </div>

      <div className="mt-4 rounded-[20px] border border-border/65 bg-background/75 p-4">
        <label htmlFor={`intuition-reflection-${questionId}`} className="text-sm font-semibold">
          一句话反思
        </label>
        <Textarea
          id={`intuition-reflection-${questionId}`}
          aria-label="一句话反思"
          value={reflection}
          onChange={(event) => setReflection(event.target.value)}
          placeholder="我的第一感觉抓住了什么？偏差又来自哪里？"
          className="mt-2 min-h-20 rounded-2xl"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-muted-foreground">全部阶段先作答后，才会显示原题答案与解析。</span>
          <Button
            type="button"
            size="sm"
            className="rounded-full"
            disabled={!allAttempted || saveStatus === 'saving'}
            onClick={() => void completePractice()}
          >
            <CheckCircle2 className="h-3.5 w-3.5" />
            完成练习，查看答案与解析
          </Button>
        </div>
      </div>
    </section>
  )
}
