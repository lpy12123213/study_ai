import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { shareApi } from '@/api/share'
import { Markdown } from '@/components/shared/Markdown'

export default function SharePage() {
  const { token } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['share', token],
    queryFn: () => shareApi.get(token!).then((r) => r.data),
  })

  if (isLoading) return <div className="flex h-screen items-center justify-center text-muted-foreground text-sm">加载中...</div>

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-4">
      <h1 className="text-2xl font-semibold">{data?.title ?? '分享内容'}</h1>
      <div className="border rounded-lg p-6 bg-card">
        <Markdown content={data?.content ?? ''} />
      </div>
    </div>
  )
}
