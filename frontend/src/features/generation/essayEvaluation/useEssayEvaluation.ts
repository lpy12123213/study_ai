import { useCallback, useState } from 'react'
import {
  type EssayEvaluationRequest,
  type EssayEvaluationResult,
  evaluateEssay,
} from '@/api/essayEvaluations'

/**
 * Synchronous essay-evaluation hook.
 *
 * Wraps the ``POST /essay-evaluations/evaluate`` API into ``{loading, error,
 * result, evaluate}`` so pages can render the result inline without hand-rolling
 * the request lifecycle. For streaming progress (long essays) submit through
 * the canonical tasks endpoint and reuse the existing tasks-SSE infrastructure.
 */
export function useEssayEvaluation() {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<EssayEvaluationResult | null>(null)
  const [evaluationId, setEvaluationId] = useState<number | null>(null)

  const evaluate = useCallback(async (payload: EssayEvaluationRequest) => {
    setLoading(true)
    setError(null)
    try {
      const response = await evaluateEssay(payload)
      setResult(response.result)
      setEvaluationId(response.evaluation_id)
      return response
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : 'evaluation_failed'
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
    evaluate,
    reset: () => {
      setError(null)
      setResult(null)
      setEvaluationId(null)
    },
  }
}
