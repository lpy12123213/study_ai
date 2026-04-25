import { apiClient } from './client'
import type { User } from '@/types'

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  user: User
  token: string
}

interface BackendLoginResponse {
  access_token: string
  token_type: string
  user_id: string
  username: string
  role: string
}

export interface RegisterRequest {
  username: string
  password: string
  email?: string
}

export async function login(data: LoginRequest): Promise<LoginResponse> {
  const response = await apiClient.post<BackendLoginResponse>('/auth/login', data)
  const payload = response.data
  return {
    token: payload.access_token,
    user: {
      id: payload.user_id,
      username: payload.username,
      role: payload.role,
    },
  }
}

export async function register(data: RegisterRequest): Promise<LoginResponse> {
  await apiClient.post('/auth/register', {
    username: data.username,
    password: data.password,
    role: 'user',
  })
  return login({ username: data.username, password: data.password })
}

export async function logout(): Promise<void> {
  return
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

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  await apiClient.post('/auth/change-password', {
    old_password: oldPassword,
    new_password: newPassword,
  })
}

export async function updateProfile(_data: Partial<User>): Promise<User> {
  throw new Error('updateProfile_not_supported')
}
