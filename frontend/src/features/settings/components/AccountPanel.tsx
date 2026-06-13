import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import type { User } from '@/types'

const roleLabels: Record<string, string> = {
  admin: '管理员',
  user: '普通用户',
}

export function AccountPanel({ user }: { user: User | null }) {
  const role = String(user?.role || '').trim().toLowerCase()
  const roleLabel = role ? roleLabels[role] || String(user?.role || '普通用户') : '普通用户'

  return (
    <div className="aurora-settings-panel space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      <div>
        <h2 className="text-lg font-medium">账户信息</h2>
        <p className="text-sm text-muted-foreground">查看和管理你的个人资料</p>
      </div>
      <Separator />
      {user ? (
        <div className="space-y-6">
          <div className="aurora-settings-account-card flex items-center gap-4">
            <div className="aurora-settings-avatar h-20 w-20 rounded-full text-primary flex items-center justify-center text-2xl font-bold">
              {user.username.charAt(0).toUpperCase()}
            </div>
            <div>
              <h3 className="font-semibold text-lg">{user.username}</h3>
              {user.email && <p className="text-sm text-muted-foreground">{user.email}</p>}
              <Badge variant="outline" className="mt-2">
                {roleLabel}
              </Badge>
            </div>
          </div>

          <p className="text-sm text-muted-foreground">当前为本地模式，无需登录。</p>
        </div>
      ) : (
        <div className="aurora-settings-empty text-center py-8 rounded-lg border border-dashed">
          <p className="text-muted-foreground">当前为本地模式，无需登录。</p>
        </div>
      )}
    </div>
  )
}
