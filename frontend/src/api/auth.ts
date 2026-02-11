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

// Login
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

// Register
export async function register(data: RegisterRequest): Promise<LoginResponse> {
  // Note: backend `/auth/register` is admin-only. Keep the API for completeness but
  // fall back to login for user experience when possible.
  await apiClient.post('/auth/register', {
    username: data.username,
    password: data.password,
    role: 'user',
  })
  return login({ username: data.username, password: data.password })
}

// Logout
export async function logout(): Promise<void> {
  // JWT is stateless; client-side logout clears local storage.
  return
}

// Get current user
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

// Update user profile
export async function updateProfile(_data: Partial<User>): Promise<User> {
  // Not implemented by backend yet.
  throw new Error('updateProfile_not_supported')
}
