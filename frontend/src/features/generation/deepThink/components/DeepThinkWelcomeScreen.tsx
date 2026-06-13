
import { Brain, Network, Sparkles } from 'lucide-react'

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
  const metrics = [
    { label: '搜索', value: '分支探索' },
    { label: '剪枝', value: '评分回溯' },
    { label: '产出', value: '路径 + 答案' },
  ]

  return (
    <div className="aurora-deep-welcome flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="aurora-deep-orb">
          <Brain className="h-10 w-10 text-primary" />
        </div>
        <div className="aurora-kicker">
          <Sparkles className="h-3.5 w-3.5" />
          Deep Think Engine
        </div>
        <div className="space-y-2">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">把题目发我，我用“思维树”来解</h2>
          <div className="text-sm leading-7 text-muted-foreground max-w-xl">
            会尝试多个解题分支、评分剪枝并回溯，最后给出更稳的解答。你也可以展开思维树，看每一步是怎么选出来的。
          </div>
        </div>
      </div>

      <div className="aurora-deep-welcome-metrics mb-8 grid w-full max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
        {metrics.map((item) => (
          <div key={item.label} className="aurora-deep-welcome-metric">
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl w-full">
        {examples.map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="aurora-deep-example group relative flex h-auto flex-col items-start p-4 text-left transition-all duration-200 hover:-translate-y-1"
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-background/70 transition-colors group-hover:bg-primary/10">
              <Network className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-3">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}
