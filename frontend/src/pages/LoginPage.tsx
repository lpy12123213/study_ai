import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Loader2, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { useAuthStore } from '@/stores/useAuthStore'
import * as authApi from '@/api/auth'
import { BrandMark } from '@/components/shared/BrandMark'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login: setAuth, isAuthenticated, token } = useAuthStore()
  
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')

  useEffect(() => {
    if (!isAuthenticated || !token) return
    const next = (location.state as any)?.from || '/chat'
    navigate(next, { replace: true })
  }, [isAuthenticated, token, location.state, navigate])

  const handleLogin = async (e: React.FormEvent) => {
    e?.preventDefault()
    setError('')
    setIsLoading(true)

    try {
      const response = await authApi.login({
        username: loginUsername,
        password: loginPassword,
      })
      setAuth(response.user, response.token)
      const next = (location.state as any)?.from || '/chat'
      navigate(next, { replace: true })
    } catch (err) {
      setError('登录失败，请检查用户名和密码')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-background relative overflow-hidden">
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-primary/5 via-background to-background" />
      
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-md relative z-10"
      >
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center h-20 w-20 rounded-3xl bg-gradient-to-br from-primary/10 to-primary/5 mb-6 ring-1 ring-border/50 shadow-sm">
            <BrandMark size={48} />
          </div>
          <h1 className="text-3xl font-bold tracking-tight mb-2">欢迎回来</h1>
          <p className="text-muted-foreground">
            登录以继续使用 AI 学习助手
          </p>
        </div>

        <Card className="border-border/50 shadow-lg">
          <CardContent className="pt-6">
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  用户名
                </label>
                <Input
                  placeholder="请输入用户名"
                  value={loginUsername}
                  onChange={(e) => setLoginUsername(e.target.value)}
                  required
                  className="bg-muted/30"
                />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
                  密码
                </label>
                <Input
                  type="password"
                  placeholder="请输入密码"
                  value={loginPassword}
                  onChange={(e) => setLoginPassword(e.target.value)}
                  required
                  className="bg-muted/30"
                />
              </div>

              {error && (
                <div className="text-sm text-destructive bg-destructive/10 p-3 rounded-md">
                  {error}
                </div>
              )}

              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    登录
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </>
                )}
              </Button>
            </form>
            <p className="mt-4 text-xs text-muted-foreground/70">
              提示：本地默认管理员账号可在 <code>.env</code> 中配置（例如 <code>admin</code> / <code>admin123</code>）。
            </p>
          </CardContent>
        </Card>
        
        <div className="text-center mt-8 text-xs text-muted-foreground/50">
          © 2024 AI Study Assistant. All rights reserved.
        </div>
      </motion.div>
    </div>
  )
}
