import { apiClient } from '@/api/client'

export type ModelSettingsProvider = {
  name: string
  base_url: string
  api_key_set: boolean
  api_key_mask: string
  api_key_encrypted: boolean
}

export type ModelSettingsResponse = {
  active_provider: string
  pinned: boolean
  providers: ModelSettingsProvider[]
  models: Record<string, unknown>
  params: Record<string, unknown>
  config_path?: string
  runtime?: {
    reloaded?: boolean
    active_provider?: string
    main_model?: string
    sub_model?: string
  }
}

export type ModelOption = {
  id: string
  owned_by?: string
}

export type FetchModelsResponse = {
  models: ModelOption[]
  count: number
  url: string
}

export type SaveModelSettingsPayload = {
  active_provider: string
  pinned: boolean
  provider: {
    name: string
    base_url: string
    api_key?: string
    clear_api_key?: boolean
  }
  models: {
    main?: string
    sub?: string
    lesson_plan?: string
  }
  params?: Record<string, unknown>
}

export async function getModelSettings(): Promise<ModelSettingsResponse> {
  const res = await apiClient.get('/model-settings')
  return res.data as ModelSettingsResponse
}

export async function saveModelSettings(payload: SaveModelSettingsPayload): Promise<ModelSettingsResponse> {
  const res = await apiClient.put('/model-settings', payload)
  return res.data as ModelSettingsResponse
}

export async function fetchProviderModels(payload: {
  provider?: string
  base_url: string
  api_key?: string
}): Promise<FetchModelsResponse> {
  const res = await apiClient.post('/model-settings/fetch-models', payload)
  return res.data as FetchModelsResponse
}
