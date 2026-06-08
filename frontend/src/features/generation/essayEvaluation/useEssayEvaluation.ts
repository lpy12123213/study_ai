import { useCallback, useState } from 'react'
import {
  type EssayEvaluationRecord,
  type EssayEvaluationRequest,
  type EssayEvaluationResult,
  evaluateEssay,
  getEssayEvaluation,
} from '@/api/essayEvaluations'

/**
 * Synchronous essay-evaluation hook.
 *
 * Wraps the ``POST /essay-evaluations/evaluate`` API into ``{loading, error,
 * result, evaluate}`` so pages can render the result inline without hand-rolling
 * the request lifecycle. For streaming progress (long essays) submit through
 * the canonical tasks endpoint and reuse the existing tasks-SSE infrastructure.
 */
function recordToResult(record: EssayEvaluationRecord): EssayEvaluationResult {
  return {
    score_total: record.score_total,
    score_max: record.score_max,
    grade: record.grade,
    summary: record.summary,
    strengths: record.strengths,
    weaknesses: record.weaknesses,
    suggestions: record.suggestions,
    scores: record.scores,
    paragraph_feedback: record.paragraph_feedback,
    rewrite: record.rewrite,
    model: record.model,
    language: record.language,
    essay_type: record.essay_type as EssayEvaluationResult['essay_type'],
    grade_band: record.grade_band as EssayEvaluationResult['grade_band'],
  }
}

export function useEssayEvaluation() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EssayEvaluationResult | null>(null)
  const [evaluationId, setEvaluationId] = useState<number | null>(null)
  const [essayText, setEssayText] = useState('')

  const evaluate = useCallback(async (payload: EssayEvaluationRequest) => {
    setLoading(true)
    setError(null)
    try {
      const response = await evaluateEssay(payload)
      setResult(response.result)
      setEvaluationId(response.evaluation_id)
      setEssayText(payload.text || '')
      return response
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'evaluation_failed'
      setError(message)
      throw caught
    } finally {
      setLoading(false)
    }
  }, [])

  const loadEvaluation = useCallback(async (id: number) => {
    const evaluationIdValue = Math.floor(Number(id) || 0)
    if (evaluationIdValue <= 0) throw new Error('invalid_evaluation_id')

    setLoading(true)
    setError(null)
    try {
      const record = await getEssayEvaluation(evaluationIdValue)
      setResult(recordToResult(record))
      setEvaluationId(record.id)
      setEssayText(record.essay_text || '')
      return record
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'evaluation_load_failed'
      setError(message)
      throw caught
    } finally {
      setLoading(false)
    }
  }, [])

  return {
    loading,
    error,
    result,
    evaluationId,
    essayText,
    evaluate,
    loadEvaluation,
    reset: () => {
      setError(null)
      setResult(null)
      setEvaluationId(null)
      setEssayText('')
    },
  }
}
