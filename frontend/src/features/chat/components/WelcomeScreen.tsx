
import { FileText, GraduationCap, Search, Sparkles } from 'lucide-react'
import { BrandMark } from '@/components/shared/BrandMark'

export function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  const metrics = [
    { label: '能力', value: '搜索 / 生成 / 讲解' },
    { label: '上下文', value: '会话持久化' },
    { label: '输出', value: '步骤与任务流' },
  ]

  return (
    <div className="aurora-chat-welcome flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="aurora-chat-orb">
           <BrandMark size={48} />
        </div>
        <div className="aurora-kicker">
          <Sparkles className="h-3.5 w-3.5" />
          AI Conversation Core
        </div>
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">有什么我可以帮你的吗？</h2>
      </div>

      <div className="aurora-chat-welcome-metrics mb-8 grid w-full max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
        {metrics.map((item) => (
          <div key={item.label} className="aurora-chat-welcome-metric">
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl w-full">
        {[
          { icon: Search, title: '搜索真题', desc: '帮我搜索一些高考数学真题' },
          { icon: FileText, title: '生成试卷', desc: '生成一份初中物理力学测试卷' },
          { icon: GraduationCap, title: '生成自学资料', desc: '帮我生成一份“函数单调性”的自学资料' },
          { icon: Sparkles, title: '概念讲解', desc: '解释一下牛顿第三定律' },
        ].map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="aurora-chat-example group relative flex h-auto flex-col items-start p-4 text-left transition-all duration-200 hover:-translate-y-1"
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-background/70 transition-colors group-hover:bg-primary/10">
              <item.icon className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
