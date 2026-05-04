import { FormEvent, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { Loader2, LogIn } from 'lucide-react'
import { login as loginRequest } from '@/api/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuthStore } from '@/stores/useAuthStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const storeLogin = useAuthStore((s) => s.login)
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  const token = useAuthStore((s) => s.token)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const redirect = searchParams.get('redirect') || '/chat'
  if (isAuthenticated && token) {
    return <Navigate to={redirect} replace />
  }

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (!username.trim() || !password) return
    setSubmitting(true)
    setError('')
    try {
      const result = await loginRequest(username.trim(), password)
      storeLogin(result.user, result.token, result.expiresAt)
      navigate(redirect, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'login_failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <form onSubmit={handleSubmit} className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-sm">
        <div className="mb-5">
          <div className="text-lg font-semibold">登录</div>
          <div className="mt-1 text-sm text-muted-foreground">Study AI</div>
        </div>

        <div className="space-y-3">
          <Input
            autoFocus
            autoComplete="username"
            placeholder="用户名"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <Input
            autoComplete="current-password"
            placeholder="密码"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </div>

        {error ? <div className="mt-3 text-sm text-destructive">{error}</div> : null}

        <Button type="submit" className="mt-5 w-full" disabled={submitting || !username.trim() || !password}>
          {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <LogIn className="mr-2 h-4 w-4" />}
          登录
        </Button>
      </form>
    </div>
  )
}
