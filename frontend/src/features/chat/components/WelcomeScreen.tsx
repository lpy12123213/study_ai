
import { FileText, GraduationCap, Search, Sparkles } from 'lucide-react'
import { BrandMark } from '@/components/shared/BrandMark'

export function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-primary/5 to-primary/10 flex items-center justify-center ring-1 ring-border/50 shadow-sm">
           <BrandMark size={48} />
        </div>
        <h2 className="text-2xl font-semibold tracking-tight">有什么我可以帮你的吗？</h2>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full">
        {[
          { icon: Search, title: '搜索真题', desc: '帮我搜索一些高考数学真题' },
          { icon: FileText, title: '生成试卷', desc: '生成一份初中物理力学测试卷' },
          { icon: GraduationCap, title: '生成自学资料', desc: '帮我生成一份“函数单调性”的自学资料' },
          { icon: Sparkles, title: '概念讲解', desc: '解释一下牛顿第三定律' },
        ].map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="group relative flex flex-col items-start p-4 h-auto text-left rounded-xl border bg-card hover:bg-accent/50 hover:border-accent transition-all duration-200 hover:-translate-y-0.5 shadow-sm hover:shadow-md"
          >
            <div className="mb-3 rounded-lg bg-muted p-2 group-hover:bg-background transition-colors">
              <item.icon className="h-4 w-4 text-muted-foreground group-hover:text-foreground" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
