import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useStickToBottom } from '@/hooks/useStickToBottom'
import { useAuthStore } from '@/stores/useAuthStore'
import { useConversationStore } from '@/stores/useConversationStore'
import { useStudyMaterialsDraftOptions } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsDraftOptions'
import { useStudyMaterialsLatexExport } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsLatexExport'
import { useStudyMaterialsSubAgentPane } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsSubAgentPane'
import { useStudyMaterialsResumableStream } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsResumableStream'
import { useStudyMaterialsStreamRunner } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsStreamRunner'
import { useStudyMaterialsTimeline } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsTimeline'
import { useStudyMaterialsActions } from '@/features/generation/studyMaterials/hooks/useStudyMaterialsActions'

export function useStudyMaterialsController() {
  const stick = useStickToBottom({ thresholdPx: 120 })
  const scrollRef = stick.containerRef
  const userId = useAuthStore((s) => s.user?.id || '')
  const [searchParams, setSearchParams] = useSearchParams()
  const reuseTaskId = String(searchParams.get('reuse_task') || '').trim()

  const [isGeneratingLocal, setIsGeneratingLocal] = useState(false)
  const [error, setError] = useState<unknown>(null)

  const {
    conversations,
    currentConversationId,
    messagesByConversation,
    lessonPlansById,
    activeConversationId,
    activeConversation,
    activeStream,
    hasResumableStream,
    lastTask,
    isLastExportFailure,
    lastTaskStatus,
    lastTaskStatusError,
    messages,
  } = useStudyMaterialsTimeline({ stick })

  const setCurrentConversation = useConversationStore((state) => state.setCurrentConversation)

  const isGenerating = isGeneratingLocal

  const {
    input,
    setInput,
    optionsOpen,
    setOptionsOpen,
    subject,
    setSubject,
    preset,
    setPreset,
    requirements,
    setRequirements,
    withQuestions,
    setWithQuestions,
    withDiagrams,
    setWithDiagrams,
    enableExtraTools,
    setEnableExtraTools,
    maxPoints,
    setMaxPoints,
    clearDraft,
  } = useStudyMaterialsDraftOptions({
    userId,
    activeConversationId,
    isGenerating: isGeneratingLocal,
    reuseTaskId,
    searchParams,
    setSearchParams,
    setCurrentConversation,
  })

  const {
    subAgentActivities,
    setSubAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    subAgentCollapsed,
    setSubAgentCollapsed,
    hasSubAgentPane,
  } = useStudyMaterialsSubAgentPane({
    activeConversationId,
    isStreaming: isGeneratingLocal,
  })

  const { abortActiveStream, runStudyMaterialsStream, streamKeyRef } = useStudyMaterialsStreamRunner({
    setIsGeneratingLocal,
    setError,
    setSubAgentActivities,
    setActiveSubAgentTab,
  })

  const { resumeStudyMaterialsStreamWithProbe, stopGenerating, resumeActiveStream, discardResumableStream } =
    useStudyMaterialsResumableStream({
      activeConversationId,
      activeStream,
      isStreaming: isGeneratingLocal,
      streamKeyRef,
      runStudyMaterialsStream,
      abortActiveStream,
      setError,
    })

  const latex = useStudyMaterialsLatexExport({
    defaultSubject: subject.trim() || '高中数学',
    lessonPlansById,
    conversations,
    messagesByConversation,
  })

  const {
    textareaRef,
    containerRef,
    leftRatio,
    setLeftRatio,
    handleDrag,
    handleNewConversation,
    handleSubmit,
    startContinueIteration,
    handleKeyDown,
  } = useStudyMaterialsActions({
    stick,
    activeConversationId,
    activeStream,
    lastTask,
    isGenerating,
    input,
    setInput,
    clearDraft,
    subject,
    preset,
    requirements,
    withQuestions,
    withDiagrams,
    enableExtraTools,
    maxPoints,
    setSubAgentActivities,
    setActiveSubAgentTab,
    runStudyMaterialsStream,
    abortActiveStream,
    resumeStudyMaterialsStreamWithProbe,
    setError,
  })

  const showSplitPane = hasSubAgentPane && !subAgentCollapsed

  return {
    scrollRef,
    isNearBottom: stick.isNearBottom,
    scrollToBottom: () => {
      stick.scrollToBottom('smooth')
      stick.setShouldStick(true)
    },
    textareaRef,
    containerRef,
    input,
    setInput,
    isGeneratingLocal,
    isGenerating,
    error,
    clearError: () => setError(null),
    leftRatio,
    setLeftRatio,
    subAgentActivities,
    setSubAgentActivities,
    activeSubAgentTab,
    setActiveSubAgentTab,
    subAgentCollapsed,
    setSubAgentCollapsed,
    hasSubAgentPane,
    showSplitPane,
    optionsOpen,
    setOptionsOpen,
    subject,
    setSubject,
    preset,
    setPreset,
    requirements,
    setRequirements,
    withQuestions,
    setWithQuestions,
    withDiagrams,
    setWithDiagrams,
    enableExtraTools,
    setEnableExtraTools,
    maxPoints,
    setMaxPoints,
    ...latex,
    conversations,
    currentConversationId,
    activeConversationId,
    activeConversation,
    lastTaskStatus,
    lastTaskStatusError,
    messagesByConversation,
    messages,
    hasResumableStream,
    isLastExportFailure,
    handleMessageScroll: stick.onScroll,
    abortActiveStream,
    stopGenerating,
    resumeActiveStream,
    discardResumableStream,
    handleDrag,
    handleNewConversation,
    handleSubmit,
    resumeStudyMaterialsStreamWithProbe,
    startContinueIteration,
    handleKeyDown,
  }
}

export type StudyMaterialsController = ReturnType<typeof useStudyMaterialsController>
