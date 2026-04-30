import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login as loginApi } from '@/api/auth'
import { useAuthStore } from '@/stores/useAuthStore'

export default function LoginPage() {
  const navigate = useNavigate()
  const storeLogin = useAuthStore((s) => s.login)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const { user, token } = await loginApi({ username, password })
      storeLogin(user, token)
      navigate('/dashboard')
    } catch {
      setError('用户名或密码错误')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex bg-background">
      <div className="hidden lg:flex flex-col justify-between w-1/2 bg-foreground text-background p-12">
        <div className="text-lg font-semibold tracking-tight">试卷助手</div>
        <div>
          <p className="text-3xl font-bold leading-snug mb-4">
            AI 驱动的<br />智能出题平台
          </p>
          <p className="text-background/60 text-sm leading-relaxed">
            自动生成试卷、深度解题分析、个性化学习计划，<br />让教学更高效。
          </p>
        </div>
        <p className="text-background/30 text-xs">© 2026 试卷助手</p>
      </div>

      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <h2 className="text-2xl font-bold tracking-tight">欢迎回来</h2>
            <p className="text-muted-foreground text-sm mt-1">登录您的账户继续使用</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">用户名</label>
              <input
                className="w-full border bg-background rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring transition-shadow"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                autoFocus
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-sm font-medium">密码</label>
              <input
                type="password"
                className="w-full border bg-background rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring transition-shadow"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
              />
            </div>
            {error && (
              <div className="text-sm text-destructive bg-destructive/10 rounded-lg px-3 py-2">
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={loading || !username || !password}
              className="w-full bg-primary text-primary-foreground rounded-lg py-2.5 text-sm font-medium hover:opacity-90 disabled:opacity-40 transition-opacity mt-2"
            >
              {loading ? '登录中...' : '登录'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
