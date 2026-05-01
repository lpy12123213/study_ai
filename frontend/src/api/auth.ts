import { apiClient } from './client'
import type { User } from '@/types'

const LOCAL_USER: User = {
  id: 'local-user',
  username: '本地用户',
  role: 'admin',
}

export async function logout(): Promise<void> {
  return
}

export async function getCurrentUser(): Promise<User> {
  try {
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
  } catch {
    return LOCAL_USER
  }
}

export async function updateProfile(_data: Partial<User>): Promise<User> {
  throw new Error('updateProfile_not_supported')
}
