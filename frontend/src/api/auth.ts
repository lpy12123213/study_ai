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

export interface RegisterRequest {
  username: string
  password: string
  email?: string
}

// Login
export async function login(data: LoginRequest): Promise<LoginResponse> {
  const response = await apiClient.post<LoginResponse>('/auth/login', data)
  return response.data
}

// Register
export async function register(data: RegisterRequest): Promise<LoginResponse> {
  const response = await apiClient.post<LoginResponse>('/auth/register', data)
  return response.data
}

// Logout
export async function logout(): Promise<void> {
  await apiClient.post('/auth/logout')
}

// Get current user
export async function getCurrentUser(): Promise<User> {
  const response = await apiClient.get<User>('/auth/me')
  return response.data
}

// Update user profile
export async function updateProfile(data: Partial<User>): Promise<User> {
  const response = await apiClient.patch<User>('/auth/me', data)
  return response.data
}
