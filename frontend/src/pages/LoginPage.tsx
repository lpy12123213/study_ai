import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Loader2, UserPlus, ArrowRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuthStore } from '@/stores/useAuthStore'
import * as authApi from '@/api/auth'
import { BrandMark } from '@/components/shared/BrandMark'

export default function LoginPage() {
  const navigate = useNavigate()
  const { login: setAuth } = useAuthStore()
  
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  
  const [loginUsername, setLoginUsername] = useState('')
  const [loginPassword, setLoginPassword] = useState('')
  
  const [registerUsername, setRegisterUsername] = useState('')
  const [registerEmail, setRegisterEmail] = useState('')
  const [registerPassword, setRegisterPassword] = useState('')
  const [registerConfirmPassword, setRegisterConfirmPassword] = useState('')

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
      navigate('/chat')
    } catch (err) {
      setError('登录失败，请检查用户名和密码')
    } finally {
      setIsLoading(false)
    }
  }

  const handleRegister = async (e: React.FormEvent) => {
    e?.preventDefault()
    setError('')

    if (registerPassword !== registerConfirmPassword) {
      setError('两次输入的密码不一致')
      return
    }

    setIsLoading(true)

    try {
      const response = await authApi.register({
        username: registerUsername,
        password: registerPassword,
        email: registerEmail || undefined,
      })
      setAuth(response.user, response.token)
      navigate('/chat')
    } catch (err) {
      setError('注册失败，用户名可能已被使用')
    } finally {
      setIsLoading(false)
    }
  }

  const handleGuestLogin = () => {
    setAuth(
      { id: 'guest', username: '访客' },
      'guest-token'
    )
    navigate('/chat')
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
            <Tabs defaultValue="login">
              <TabsList className="grid w-full grid-cols-2 mb-6">
                <TabsTrigger value="login">登录</TabsTrigger>
                <TabsTrigger value="register">注册</TabsTrigger>
              </TabsList>

              <TabsContent value="login">
                <form onSubmit={handleLogin} className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">用户名</label>
                    <Input
                      placeholder="请输入用户名"
                      value={loginUsername}
                      onChange={(e) => setLoginUsername(e.target.value)}
                      required
                      className="bg-muted/30"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">密码</label>
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
              </TabsContent>

              <TabsContent value="register">
                <form onSubmit={handleRegister} className="space-y-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none">用户名</label>
                    <Input
                      placeholder="设置用户名"
                      value={registerUsername}
                      onChange={(e) => setRegisterUsername(e.target.value)}
                      required
                      className="bg-muted/30"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none">邮箱 (可选)</label>
                    <Input
                      type="email"
                      placeholder="example@email.com"
                      value={registerEmail}
                      onChange={(e) => setRegisterEmail(e.target.value)}
                      className="bg-muted/30"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none">密码</label>
                    <Input
                      type="password"
                      placeholder="设置密码"
                      value={registerPassword}
                      onChange={(e) => setRegisterPassword(e.target.value)}
                      required
                      className="bg-muted/30"
                    />
                  </div>
                  <div className="space-y-2">
                    <label className="text-sm font-medium leading-none">确认密码</label>
                    <Input
                      type="password"
                      placeholder="再次输入密码"
                      value={registerConfirmPassword}
                      onChange={(e) => setRegisterConfirmPassword(e.target.value)}
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
                        注册账户
                        <UserPlus className="ml-2 h-4 w-4" />
                      </>
                    )}
                  </Button>
                </form>
              </TabsContent>
            </Tabs>

            <div className="relative my-8">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-border" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-card px-2 text-muted-foreground">或者</span>
              </div>
            </div>

            <Button
              variant="outline"
              className="w-full bg-muted/30 hover:bg-muted/50"
              onClick={handleGuestLogin}
            >
              访客模式体验
            </Button>
          </CardContent>
        </Card>
        
        <div className="text-center mt-8 text-xs text-muted-foreground/50">
          © 2024 AI Study Assistant. All rights reserved.
        </div>
      </motion.div>
    </div>
  )
}
