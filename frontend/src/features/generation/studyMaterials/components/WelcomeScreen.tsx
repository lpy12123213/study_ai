import { BookOpen, Layers, Search, Sparkles } from 'lucide-react'

type WelcomeExample = { title: string; desc: string }

function inferWelcomeSubjectKey(subject: string): string {
  const value = String(subject || '').trim().toLowerCase()
  if (!value) return 'default'

  if (value.includes('数学') || value.includes('math')) return 'math'
  if (value.includes('物理') || value.includes('physics')) return 'physics'
  if (value.includes('化学') || value.includes('chem')) return 'chemistry'
  if (value.includes('生物') || value.includes('biology')) return 'biology'
  if (value.includes('英语') || value.includes('英文') || value.includes('english')) return 'english'
  if (value.includes('语文') || value.includes('中文') || value.includes('chinese')) return 'chinese'

  return 'default'
}

function getWelcomeExamples(subject: string): WelcomeExample[] {
  const key = inferWelcomeSubjectKey(subject)

  if (key === 'math') {
    return [
      { title: '函数单调性', desc: '高中数学：定义法与典型例题' },
      { title: '二次函数最值', desc: '配方法/判别式/图像理解' },
      { title: '导数求极值', desc: '求导、临界点、最值判定' },
      { title: '数列求和', desc: '等差/等比/错位相减' },
    ]
  }
  if (key === 'physics') {
    return [
      { title: '受力分析', desc: '受力图、正交分解、常见陷阱' },
      { title: '动量守恒', desc: '碰撞模型、系统选取、方向约定' },
      { title: '电场与电势', desc: '场强叠加、电势能、等势面' },
      { title: '电路分析', desc: '串并联、基尔霍夫定律、功率' },
    ]
  }
  if (key === 'chemistry') {
    return [
      { title: '化学平衡常数', desc: 'K 的表达式、比较与计算' },
      { title: '电化学基础', desc: '原电池/电解池、电子转移、判断' },
      { title: '酸碱滴定', desc: 'pH 计算、滴定曲线、指示剂选择' },
      { title: '氧化还原反应', desc: '配平、电子守恒、常见误区' },
    ]
  }
  if (key === 'biology') {
    return [
      { title: '细胞呼吸', desc: '有氧/无氧、能量变化、实验设计' },
      { title: '遗传规律', desc: '分离/自由组合、概率与谱系分析' },
      { title: '光合作用', desc: '光反应/暗反应、限制因素' },
      { title: '免疫调节', desc: '体液/细胞免疫、抗原抗体' },
    ]
  }
  if (key === 'english') {
    return [
      { title: '定语从句', desc: '关系词选择、限制/非限制' },
      { title: '虚拟语气', desc: 'if 从句、倒装、省略' },
      { title: '时态综合', desc: '完成时、进行时、易错点' },
      { title: '阅读理解主旨', desc: '主题句定位、选项排除' },
    ]
  }
  if (key === 'chinese') {
    return [
      { title: '文言文实词虚词', desc: '常见义项、句式、断句技巧' },
      { title: '现代文阅读概括', desc: '要点提取、结构梳理、答题模板' },
      { title: '诗歌鉴赏意象', desc: '意境、手法、表达效果' },
      { title: '作文立意与结构', desc: '审题立意、论证结构、素材组织' },
    ]
  }

  return [
    { title: '函数单调性', desc: '高中数学：定义法与典型例题' },
    { title: '受力分析', desc: '受力图、正交分解、常见陷阱' },
    { title: '化学平衡常数', desc: 'K 的表达式、比较与计算' },
    { title: '定语从句', desc: '关系词选择、限制/非限制' },
  ]
}

export function WelcomeScreen({
  subject,
  onExampleClick,
}: {
  subject: string
  onExampleClick: (text: string) => void
}) {
  const examples = getWelcomeExamples(subject)
  const metrics = [
    { label: '检索编队', value: '题库 + 资料' },
    { label: '生成模式', value: '讲解 + 例题' },
    { label: '输出形态', value: 'Markdown / LaTeX' },
  ]

  return (
    <div className="aurora-materials-welcome flex-1 flex flex-col items-center justify-center p-8 animate-in fade-in duration-500">
      <div className="mb-10 flex flex-col items-center text-center space-y-6">
        <div className="aurora-materials-orb">
          <BookOpen className="h-10 w-10 text-primary" strokeWidth={1.5} />
        </div>
        <div className="aurora-kicker">
          <Sparkles className="h-3.5 w-3.5" />
          Study Materials Forge
        </div>
        <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">自学资料生成舱</h2>
        <p className="max-w-xl text-sm leading-7 text-muted-foreground sm:text-base">
          输入你想学的知识点（例如“函数单调性”），我将为你检索题目、生成讲解与例题步骤。
        </p>
      </div>

      <div className="aurora-materials-metrics mb-8 grid w-full max-w-3xl grid-cols-1 gap-3 sm:grid-cols-3">
        {metrics.map((item, index) => (
          <div key={item.label} className="aurora-materials-metric" style={{ animationDelay: `${index * 70}ms` }}>
            <div className="text-[10px] uppercase tracking-[0.28em] text-muted-foreground">{item.label}</div>
            <div className="mt-1 text-sm font-semibold text-foreground">{item.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl w-full">
        {examples.map((item) => (
          <button
            key={item.title}
            onClick={() => onExampleClick(item.title)}
            className="aurora-materials-example group relative flex h-auto flex-col items-start p-4 text-left transition-all duration-200 hover:-translate-y-1"
          >
            <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-xl bg-background/70 transition-colors group-hover:bg-primary/10">
              {item.title.length % 2 === 0 ? (
                <Search className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
              ) : (
                <Layers className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
              )}
            </div>
            <div className="font-medium text-sm mb-1">{item.title}</div>
            <div className="text-xs text-muted-foreground line-clamp-2">{item.desc}</div>
          </button>
        ))}
      </div>
    </div>
  )
}

