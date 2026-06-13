import { BookOpenCheck, Layers, Sparkles } from 'lucide-react'

export function WelcomeScreen({ onExampleClick }: { onExampleClick: (text: string) => void }) {
  const metrics = [
    { label: '输入', value: '学科/年级/课题' },
    { label: '编排', value: '目标/活动/练习' },
    { label: '输出', value: '教案卡 + 详情' },
  ]

  return (
    <div className="aurora-lesson-welcome flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="aurora-lesson-orb">
          <BookOpenCheck className="h-10 w-10 text-primary" strokeWidth={1.5} />
        </div>
        <div className="aurora-kicker">
          <Sparkles className="h-3.5 w-3.5" />
          Lesson Forge
        </div>
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">教案生成助手</h2>
        <p className="max-w-xl text-sm leading-7 text-muted-foreground sm:text-base">
          输入你的需求（建议包含学科/年级/课题/课时），我将为你生成一份详细的教学设计。
        </p>
      </div>

      <div className="aurora-lesson-welcome-metrics mb-8 grid w-full max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
        {metrics.map((item) => (
          <div key={item.label} className="aurora-lesson-welcome-metric">
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl w-full">
        {[
          { title: '函数与导数', desc: '高二数学：函数单调性与导数应用' },
          { title: '力学实验', desc: '高一物理：验证牛顿第二定律' },
          { title: '文言文阅读', desc: '高一语文：文言文断句与翻译' },
          { title: '化学反应速率', desc: '高二化学：影响反应速率的因素' },
        ].map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.desc)}
            className="aurora-lesson-example group relative flex h-auto flex-col items-start p-4 text-left transition-all duration-200 hover:-translate-y-1"
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-background/70 transition-colors group-hover:bg-primary/10">
              <Layers className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

