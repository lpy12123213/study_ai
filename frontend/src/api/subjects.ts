import { apiClient } from './client'
import type { Subject } from '@/types'

export interface SubjectFilters {
  grades?: { id: number; name: string }[]
  textbookVersions?: { id: string; name: string }[]
  provinces?: { id: number; name: string }[]
  paperTypes?: { id: number; name: string }[]
  questionTypes?: { id: string; name: string }[]
}

// Get all subjects
export async function getSubjects(): Promise<Subject[]> {
  const response = await apiClient.get<unknown>('/subjects')
  const data = response.data as unknown

  type BackendSubject = {
    name?: unknown
    short_name?: unknown
    bank_id?: unknown
    edu_id?: unknown
  }

  // backend returns: { subjects: [{ name, short_name, bank_id, edu_id }, ...] }
  const list: BackendSubject[] = Array.isArray(data)
    ? (data as BackendSubject[])
    : Array.isArray((data as any)?.subjects)
      ? ((data as any).subjects as BackendSubject[])
      : []

  const normalized = list
    .filter((s): s is BackendSubject & { name: string } => typeof s?.name === 'string' && s.name.trim().length > 0)
    .map((s) => {
      const name = s.name.trim()
      const shortName = typeof s.short_name === 'string' ? s.short_name.trim() : undefined
      const bankId = typeof s.bank_id === 'number' ? s.bank_id : undefined
      const eduId = typeof s.edu_id === 'number' ? s.edu_id : undefined
      return {
        id: String(bankId ?? name),
        name,
        code: name, // use full name as request value
        shortName,
        bankId,
        eduId,
      }
    })

  // Defensive de-dupe: backend bugs or legacy configs may repeat items.
  const seen = new Set<string>()
  return normalized.filter((s) => {
    const key = String(s.id || '').trim() || s.code
    if (!key) return false
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

// Get subject filters (grades, textbook versions, etc.)
export async function getSubjectFilters(
  subjectCode: string
): Promise<SubjectFilters> {
  const response = await apiClient.get<SubjectFilters>(
    `/subjects/${subjectCode}/filters`
  )
  return response.data
}
