import { apiClient } from './client'
import type { User } from '@/types'

interface LoginResponse {
  access_token: string
  token_type: string
  expires_at: number
  user: {
    user_id: string
    username: string
    role: string
    created_at?: string | null
  }
}

function toUser(input: LoginResponse['user']): User {
  return {
    id: input.user_id,
    username: input.username,
    role: input.role,
  }
}

export async function login(username: string, password: string): Promise<{ user: User; token: string; expiresAt: number }> {
  const response = await apiClient.post<LoginResponse>('/auth/login', { username, password })
  return {
    user: toUser(response.data.user),
    token: response.data.access_token,
    expiresAt: response.data.expires_at,
  }
}

export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}

export async function getCurrentUser(): Promise<User> {
  const response = await apiClient.get<{
    user_id: string
    username: string
    role: string
  }>('/auth/me')
  return {
    id: response.data.user_id,
    username: response.data.username,
    role: response.data.role,
  }
}

export async function updateProfile(_data: Partial<User>): Promise<User> {
  throw new Error('updateProfile_not_supported')
}
