
import { Brain } from 'lucide-react'

export function DeepThinkWelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  const examples = [
    {
      title: '函数与导数',
      desc: '已知函数 f(x)=x^3-3x^2+2，求极值与单调区间。',
    },
    {
      title: '解析几何',
      desc: '已知椭圆 x^2/4+y^2=1，求过点(0,2)的切线方程。',
    },
    {
      title: '概率统计',
      desc: '袋中有3红2蓝，连续不放回抽2个，求至少抽到1个红球的概率。',
    },
    {
      title: '物理力学',
      desc: '一物体在水平面上受恒力F作用，摩擦系数μ，求加速度与位移关系。',
    },
  ]

  return (
    <div className="flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="h-20 w-20 rounded-3xl bg-gradient-to-br from-primary/5 to-primary/10 flex items-center justify-center ring-1 ring-border/50 shadow-sm">
          <Brain className="h-10 w-10 text-primary" />
        </div>
        <div className="space-y-2">
          <h2 className="text-2xl font-semibold tracking-tight">把题目发我，我用“思维树”来解</h2>
          <div className="text-sm text-muted-foreground max-w-xl">
            会尝试多个解题分支、评分剪枝并回溯，最后给出更稳的解答。你也可以展开思维树，看每一步是怎么选出来的。
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-2xl w-full">
        {examples.map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="group relative flex flex-col items-start p-4 h-auto text-left rounded-xl border bg-card hover:bg-accent/50 hover:border-accent transition-all duration-200 hover:-translate-y-0.5 shadow-sm hover:shadow-md"
          >
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-3">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
