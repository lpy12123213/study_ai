import { useState } from 'react'
import { useAuthStore } from '@/stores/useAuthStore'
import { useThemeStore } from '@/stores/useThemeStore'
import { changePassword } from '@/api/auth'

export default function SettingsPage() {
  const user = useAuthStore((s) => s.user)
  const { theme, toggleTheme } = useThemeStore()
  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [msg, setMsg] = useState('')

  const handleChangePassword = async () => {
    try {
      await changePassword(oldPwd, newPwd)
      setMsg('密码修改成功')
      setOldPwd(''); setNewPwd('')
    } catch {
      setMsg('修改失败，请检查原密码')
    }
  }

  return (
    <div className="space-y-8 max-w-lg">
      <h1 className="text-2xl font-semibold">设置</h1>
      <div className="space-y-2">
        <h2 className="font-medium">账户</h2>
        <p className="text-sm text-muted-foreground">用户名：{user?.username}　角色：{user?.role}</p>
      </div>
      <div className="space-y-3">
        <h2 className="font-medium">外观</h2>
        <div className="flex items-center gap-3">
          <span className="text-sm">主题</span>
          <button onClick={toggleTheme} className="px-3 py-1.5 border rounded-md text-sm hover:bg-accent transition-colors">
            {theme === 'dark' ? '切换到浅色' : '切换到深色'}
          </button>
        </div>
      </div>
      <div className="space-y-3">
        <h2 className="font-medium">修改密码</h2>
        <input type="password" className="w-full border rounded-md px-3 py-2 text-sm bg-background" placeholder="原密码" value={oldPwd} onChange={(e) => setOldPwd(e.target.value)} />
        <input type="password" className="w-full border rounded-md px-3 py-2 text-sm bg-background" placeholder="新密码" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} />
        {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
        <button onClick={handleChangePassword} disabled={!oldPwd || !newPwd} className="px-4 py-2 bg-primary text-primary-foreground rounded-md text-sm disabled:opacity-50">保存</button>
      </div>
    </div>
  )
}
