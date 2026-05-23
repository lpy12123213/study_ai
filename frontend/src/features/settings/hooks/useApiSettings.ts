import { useCallback, useState } from 'react'
import * as modelSettingsApi from '@/api/modelSettings'
import type { ModelOption, ModelSettingsResponse } from '@/api/modelSettings'
import { isRecord } from '@/lib/record'

export type ApiSettingsState = {
  providerName: string
  providerBaseUrl: string
  providerApiKey: string
  savedApiKeyMask: string
  savedApiKeyEncrypted: boolean
  showProviderApiKey: boolean
  mainModel: string
  subModel: string
  lessonPlanModel: string
  providerPinned: boolean
  modelOptions: ModelOption[]
  modelSettingsLoaded: boolean
  isModelLoading: boolean
  isFetchingModels: boolean
  isSavingModelSettings: boolean
  modelSettingsMessage: string
}

export type ApiSettingsActions = {
  setProviderName: (next: string) => void
  setProviderBaseUrl: (next: string) => void
  setProviderApiKey: (next: string) => void
  toggleShowApiKey: () => void
  setMainModel: (next: string) => void
  setSubModel: (next: string) => void
  setLessonPlanModel: (next: string) => void
  setProviderPinned: (next: boolean) => void
  loadModelSettings: () => Promise<void>
  fetchProviderModels: () => Promise<void>
  saveModelSettings: () => Promise<void>
}

export type ApiSettingsHook = ApiSettingsState & ApiSettingsActions

function pickScopedModel(value: unknown, provider: string): string {
  if (typeof value === 'string') return value.trim()
  if (!isRecord(value)) return ''
  const providerValue = value[provider]
  if (typeof providerValue === 'string' && providerValue.trim()) return providerValue.trim()
  const defaultValue = value.default
  if (typeof defaultValue === 'string' && defaultValue.trim()) return defaultValue.trim()
  for (const item of Object.values(value)) {
    if (typeof item === 'string' && item.trim()) return item.trim()
  }
  return ''
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message
  if (isRecord(error) && typeof error.message === 'string' && error.message.trim()) return error.message
  return '操作失败'
}

/**
 * Encapsulate the "model connection" panel state: provider config, API key,
 * model picker, and the load/fetch/save lifecycle. Keeping the controller
 * here lets the panel render as a pure presentational component.
 */
export function useApiSettings(): ApiSettingsHook {
  const [providerName, setProviderName] = useState('')
  const [providerBaseUrl, setProviderBaseUrl] = useState('')
  const [providerApiKey, setProviderApiKey] = useState('')
  const [savedApiKeyMask, setSavedApiKeyMask] = useState('')
  const [savedApiKeyEncrypted, setSavedApiKeyEncrypted] = useState(false)
  const [showProviderApiKey, setShowProviderApiKey] = useState(false)
  const [mainModel, setMainModel] = useState('')
  const [subModel, setSubModel] = useState('')
  const [lessonPlanModel, setLessonPlanModel] = useState('')
  const [providerPinned, setProviderPinned] = useState(true)
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([])
  const [modelSettingsLoaded, setModelSettingsLoaded] = useState(false)
  const [isModelLoading, setIsModelLoading] = useState(false)
  const [isFetchingModels, setIsFetchingModels] = useState(false)
  const [isSavingModelSettings, setIsSavingModelSettings] = useState(false)
  const [modelSettingsMessage, setModelSettingsMessage] = useState('')

  const applyResponse = useCallback((res: ModelSettingsResponse) => {
    const active = String(res.active_provider || '').trim()
    const provider = (res.providers || []).find((item) => item.name === active) || (res.providers || [])[0]
    const providerValue = String(provider?.name || active).trim()

    setProviderName(providerValue)
    setProviderBaseUrl(String(provider?.base_url || '').trim())
    setSavedApiKeyMask(String(provider?.api_key_mask || ''))
    setSavedApiKeyEncrypted(Boolean(provider?.api_key_encrypted))
    setProviderApiKey('')
    setProviderPinned(Boolean(res.pinned))
    setMainModel(pickScopedModel(res.models?.main, providerValue))
    setSubModel(pickScopedModel(res.models?.sub, providerValue))
    setLessonPlanModel(pickScopedModel(res.models?.lesson_plan, providerValue))
  }, [])

  const loadModelSettings = useCallback(async () => {
    setIsModelLoading(true)
    setModelSettingsMessage('')
    try {
      const res = await modelSettingsApi.getModelSettings()
      applyResponse(res)
    } catch (error) {
      setModelSettingsMessage(errorMessage(error))
    } finally {
      setModelSettingsLoaded(true)
      setIsModelLoading(false)
    }
  }, [applyResponse])

  const fetchProviderModels = useCallback(async () => {
    setIsFetchingModels(true)
    setModelSettingsMessage('')
    try {
      const res = await modelSettingsApi.fetchProviderModels({
        provider: providerName.trim(),
        base_url: providerBaseUrl.trim(),
        ...(providerApiKey.trim() ? { api_key: providerApiKey.trim() } : {}),
      })
      setModelOptions(res.models || [])
      const first = res.models?.[0]?.id || ''
      if (first) {
        if (!mainModel.trim()) setMainModel(first)
        if (!subModel.trim()) setSubModel(first)
        if (!lessonPlanModel.trim()) setLessonPlanModel(first)
      }
      setModelSettingsMessage(`已抓取 ${res.count || 0} 个模型`)
    } catch (error) {
      setModelSettingsMessage(errorMessage(error))
    } finally {
      setIsFetchingModels(false)
    }
  }, [providerName, providerBaseUrl, providerApiKey, mainModel, subModel, lessonPlanModel])

  const saveModelSettings = useCallback(async () => {
    setIsSavingModelSettings(true)
    setModelSettingsMessage('')
    try {
      const res = await modelSettingsApi.saveModelSettings({
        active_provider: providerName.trim(),
        pinned: providerPinned,
        provider: {
          name: providerName.trim(),
          base_url: providerBaseUrl.trim(),
          ...(providerApiKey.trim() ? { api_key: providerApiKey.trim() } : {}),
        },
        models: {
          main: mainModel.trim(),
          sub: subModel.trim(),
          lesson_plan: lessonPlanModel.trim(),
        },
      })
      applyResponse(res)
      setModelSettingsLoaded(true)
      setModelSettingsMessage('已加密保存并刷新运行配置')
    } catch (error) {
      setModelSettingsMessage(errorMessage(error))
    } finally {
      setIsSavingModelSettings(false)
    }
  }, [providerName, providerBaseUrl, providerApiKey, providerPinned, mainModel, subModel, lessonPlanModel, applyResponse])

  return {
    providerName,
    providerBaseUrl,
    providerApiKey,
    savedApiKeyMask,
    savedApiKeyEncrypted,
    showProviderApiKey,
    mainModel,
    subModel,
    lessonPlanModel,
    providerPinned,
    modelOptions,
    modelSettingsLoaded,
    isModelLoading,
    isFetchingModels,
    isSavingModelSettings,
    modelSettingsMessage,
    setProviderName,
    setProviderBaseUrl,
    setProviderApiKey,
    toggleShowApiKey: () => setShowProviderApiKey((v) => !v),
    setMainModel,
    setSubModel,
    setLessonPlanModel,
    setProviderPinned,
    loadModelSettings,
    fetchProviderModels,
    saveModelSettings,
  }
}
