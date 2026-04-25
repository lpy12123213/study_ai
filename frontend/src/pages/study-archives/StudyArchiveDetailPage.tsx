import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { studyArchivesApi } from '@/api/studyArchives'
import { MarkdownRenderer } from '@/components/MarkdownRenderer'

export default function StudyArchiveDetailPage() {
  const { archiveId } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['study-archives', archiveId],
    queryFn: () => studyArchivesApi.get(archiveId!).then((r) => r.data),
  })

  if (isLoading) return <div className="text-muted-foreground text-sm">加载中...</div>

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{data?.title ?? '学习档案'}</h1>
      <div className="border rounded-lg p-4 bg-card">
        <MarkdownRenderer content={data?.content ?? ''} />
      </div>
    </div>
  )
}
