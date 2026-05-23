import { useEffect, useState } from 'react'
import { useConversationStore } from '@/stores/useConversationStore'
import { extractStepKnowledgePoints, normalizeKnowledgePoints } from '@/features/generation/studyMaterials/utils'
import type { TaskStep } from '@/types'
import type { SubAgentActivity } from '@/features/generation/studyMaterials/types'

export function useStudyMaterialsSubAgentPane(opts: {
  activeConversationId: string | null
  isStreaming: boolean
}) {
  const { activeConversationId, isStreaming } = opts

  // SubAgent activities for the right panel
  const [subAgentActivities, setSubAgentActivities] = useState<SubAgentActivity[]>([])

  // Active tab in SubAgent panel
  const [activeSubAgentTab, setActiveSubAgentTab] = useState<string | null>(null)

  const [subAgentCollapsed, setSubAgentCollapsed] = useState(false)

  const hasSubAgentPane = isStreaming || subAgentActivities.length > 0

  useEffect(() => {
    if (!hasSubAgentPane) {
      setSubAgentCollapsed(false)
    }
  }, [hasSubAgentPane])

  // Reconstruct subAgentActivities from persisted messages on load / conversation switch
  useEffect(() => {
    if (!activeConversationId) return
    if (isStreaming) return // don't overwrite while streaming

    const msgs = useConversationStore.getState().getMessages(activeConversationId)
    const allSteps: TaskStep[] = []
    for (const m of msgs) {
      if (m.role === 'assistant' && Array.isArray(m.steps)) {
        allSteps.push(...m.steps)
      }
    }
    if (allSteps.length === 0) return

    // Find the split_knowledge_points result to get the full KP list
    let kpList: string[] = []
    for (const step of allSteps) {
      if (step.toolName === 'split_knowledge_points' && step.output && typeof step.output === 'object') {
        const out = step.output as Record<string, unknown>
        kpList = normalizeKnowledgePoints(out.knowledge_points)
        if (kpList.length > 0) break
      }
    }
    if (kpList.length === 0) return

    // Collect per-KP steps
    const kpStepsMap = new Map<string, TaskStep[]>()
    for (const kp of kpList) kpStepsMap.set(kp, [])

    for (const step of allSteps) {
      const stepKps = extractStepKnowledgePoints(step)
      if (stepKps.length === 1 && kpStepsMap.has(stepKps[0])) {
        kpStepsMap.get(stepKps[0])!.push(step)
      }
    }

    const activities: SubAgentActivity[] = kpList.map((kp) => {
      const steps = kpStepsMap.get(kp) || []
      let status: SubAgentActivity['status'] = 'pending'
      if (steps.length > 0) {
        const hasRunning = steps.some((s) => s.status === 'running')
        const hasFailed = steps.some((s) => s.status === 'failed')
        if (hasRunning) status = 'running'
        else if (hasFailed) status = 'failed'
        else status = 'completed'
      }
      return { knowledgePoint: kp, status, steps }
    })

    setSubAgentActivities(activities)
    setActiveSubAgentTab((prev) => prev || kpList[0])
  }, [activeConversationId, isStreaming])

  // When no conversation is selected, ensure we don't show stale activities.
  useEffect(() => {
    if (activeConversationId) return
    setSubAgentActivities([])
    setActiveSubAgentTab(null)
  }, [activeConversationId])

  return {
    subAgentActivities,
    setSubAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    subAgentCollapsed,
    setSubAgentCollapsed,
    hasSubAgentPane,
  }
}

