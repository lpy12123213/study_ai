import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useDeepThink } from '@/hooks/useDeepThink'
import type { DeepThinkMetrics, DeepThinkStatus, ThinkingNode } from '@/hooks/useDeepThink'
import { useSubjects } from '@/hooks/useSubjects'
import { generateId } from '@/lib/utils'
import type { DeepThinkChatMessage } from '../types'
import { buildConfigSummary, buildDeepStats, getAssistantIndicatorTone, getStatusLabel } from '../utils'

export type DeepThinkPageState = {
  // subjects
  subjects: ReturnType<typeof useSubjects>['data']
  subject: string
  setSubject: (value: string) => void
  imageUrl: string
  setImageUrl: (value: string) => void
  input: string
  setInput: (value: string) => void
  messages: DeepThinkChatMessage[]
  showOptions: boolean
  setShowOptions: (value: boolean | ((prev: boolean) => boolean)) => void
  showTree: boolean
  setShowTree: (value: boolean | ((prev: boolean) => boolean)) => void
  selectedNodeId: string | null
  setSelectedNodeId: (value: string | null) => void
  activeAssistantId: string | null
  // scroll
  scrollRef: React.RefObject<HTMLDivElement | null>
  showJumpToBottom: boolean
  scrollToBottom: () => void
  handleScroll: () => void
  // deepthink hook
  status: DeepThinkStatus
  taskId: string
  nodes: Record<string, ThinkingNode>
  bestPath: string[]
  answer: string
  metrics: DeepThinkMetrics
  error: string | null
  config: Record<string, unknown> | null
  isStreaming: boolean
  // derived
  selectedNode: ThinkingNode | null
  configSummary: ReturnType<typeof buildConfigSummary>
  statusLabel: string
  assistantIndicatorTone: string
  deepStats: Array<{ label: string; value: string }>
  // handlers
  handleClear: () => void
  handleSubmit: (e?: React.FormEvent) => void
  cancel: (reason: string) => void
}

export function useDeepThinkPage(): DeepThinkPageState {
  const { data: subjects } = useSubjects()
  const [subject, setSubject] = useState<string>('')
  const [imageUrl, setImageUrl] = useState<string>('')

  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<DeepThinkChatMessage[]>([])
  const [showOptions, setShowOptions] = useState(false)
  const [showTree, setShowTree] = useState(true)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [activeAssistantId, setActiveAssistantId] = useState<string | null>(null)
  const activeAssistantIdRef = useRef<string | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)
  const stickToBottomRef = useRef(true)
  const [showJumpToBottom, setShowJumpToBottom] = useState(false)

  const { status, taskId, nodes, bestPath, answer, metrics, error, config, solve, cancel, reset } = useDeepThink()
  const isStreaming = status === 'searching' || status === 'answering'

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    stickToBottomRef.current = true
    setShowJumpToBottom(false)
    requestAnimationFrame(() => {
      const target = scrollRef.current
      if (!target) return
      target.scrollTop = target.scrollHeight
    })
  }, [])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    const distanceToBottom = el.scrollHeight - (el.scrollTop + el.clientHeight)
    const nearBottom = distanceToBottom < 120
    stickToBottomRef.current = nearBottom
    setShowJumpToBottom((prev) => (prev !== !nearBottom ? !nearBottom : prev))
  }, [])

  useEffect(() => {
    if (subjects && subjects.length > 0 && !subject) {
      setSubject(subjects[0].code)
    }
  }, [subjects, subject])

  useEffect(() => {
    const id = activeAssistantIdRef.current
    if (!id) return
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, content: answer } : m)))
  }, [answer])

  useEffect(() => {
    if (!stickToBottomRef.current) return
    const el = scrollRef.current
    if (!el) return
    requestAnimationFrame(() => {
      const target = scrollRef.current
      if (!target) return
      target.scrollTop = target.scrollHeight
    })
  }, [messages])

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null
    return nodes[selectedNodeId] || null
  }, [nodes, selectedNodeId])

  const configSummary = useMemo(() => buildConfigSummary(config), [config])

  const statusLabel = getStatusLabel(status)

  const handleClear = () => {
    if (isStreaming) return
    activeAssistantIdRef.current = null
    setActiveAssistantId(null)
    setSelectedNodeId(null)
    setShowTree(true)
    setMessages([])
    reset()
  }

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    const question = input.trim()
    if (!question || isStreaming) return

    stickToBottomRef.current = true
    setShowJumpToBottom(false)

    const now = new Date().toISOString()
    const userMessage: DeepThinkChatMessage = {
      id: generateId(),
      role: 'user',
      content: question,
      createdAt: now,
      meta: {
        subject,
        imageUrl: imageUrl.trim() ? imageUrl.trim() : undefined,
      },
    }
    const assistantId = generateId()
    const assistantMessage: DeepThinkChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      createdAt: now,
    }

    activeAssistantIdRef.current = assistantId
    setActiveAssistantId(assistantId)
    setSelectedNodeId(null)
    setShowTree(true)
    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setInput('')

    solve(question, {
      subject,
      imageUrl: imageUrl.trim() ? imageUrl.trim() : undefined,
    })
  }

  const assistantIndicatorTone = getAssistantIndicatorTone(status)
  const deepStats = buildDeepStats(metrics, nodes, subject, statusLabel)

  return {
    subjects,
    subject,
    setSubject,
    imageUrl,
    setImageUrl,
    input,
    setInput,
    messages,
    showOptions,
    setShowOptions,
    showTree,
    setShowTree,
    selectedNodeId,
    setSelectedNodeId,
    activeAssistantId,
    scrollRef,
    showJumpToBottom,
    scrollToBottom,
    handleScroll,
    status,
    taskId,
    nodes,
    bestPath,
    answer,
    metrics,
    error,
    config,
    isStreaming,
    selectedNode,
    configSummary,
    statusLabel,
    assistantIndicatorTone,
    deepStats,
    handleClear,
    handleSubmit,
    cancel,
  }
}
