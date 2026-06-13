import { useQuery } from '@tanstack/react-query'
import { getLessonPlans } from '@/api/lessonPlans'
import { listStudyArchives } from '@/api/studyArchives'
import { formatDate } from '@/lib/utils'

export type MasterListKind = 'lesson-plans' | 'study-archives'

export type MasterListItem = {
  id: string
  title: string
  subtitle?: string
  to: string
}

async function loadItems(kind: MasterListKind): Promise<MasterListItem[]> {
  if (kind === 'lesson-plans') {
    const plans = await getLessonPlans()
    return plans.map((plan) => ({
      id: String(plan.id || ''),
      title: String(plan.title || '未命名教案'),
      subtitle: [plan.subject, plan.grade].filter(Boolean).join(' · ') || undefined,
      to: `/lesson-plans/${encodeURIComponent(String(plan.id || ''))}`,
    })).filter((item) => item.id)
  }

  const archives = await listStudyArchives({ limit: 80 })
  return archives.map((archive) => ({
    id: String(archive.id || ''),
    title: [archive.subject, archive.topic].filter(Boolean).join(' · ') || `学习档案 #${archive.id}`,
    subtitle: archive.updated_at || archive.created_at ? formatDate(String(archive.updated_at || archive.created_at)) : undefined,
    to: `/study-archives/${encodeURIComponent(String(archive.id || ''))}`,
  })).filter((item) => item.id)
}

export function useMasterList(kind: MasterListKind) {
  return useQuery({
    queryKey: ['workspaceSplit', kind],
    queryFn: () => loadItems(kind),
    staleTime: 30_000,
  })
}
