import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { learningPlansApi } from '@/api/learningPlans'
import { Check, Plus, Trash2 } from 'lucide-react'

export default function LearningPlansTodoPage() {
  const qc = useQueryClient()
  const [newItem, setNewItem] = useState('')
  const { data, isLoading } = useQuery({
    queryKey: ['learning-plans'],
    queryFn: () => learningPlansApi.list().then((r) => r.data),
  })
  const todos: { id: string; title: string; done: boolean }[] = data?.todos ?? data ?? []

  const add = useMutation({
    mutationFn: () => learningPlansApi.create({ title: newItem }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['learning-plans'] }); setNewItem('') },
  })
  const toggle = useMutation({
    mutationFn: ({ id, done }: { id: string; done: boolean }) => learningPlansApi.update(id, { done }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['learning-plans'] }),
  })
  const remove = useMutation({
    mutationFn: (id: string) => learningPlansApi.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['learning-plans'] }),
  })

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">学习计划</h1>
      <div className="flex gap-2">
        <input className="flex-1 border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-ring" placeholder="添加计划..." value={newItem} onChange={(e) => setNewItem(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && newItem.trim() && add.mutate()} />
        <button onClick={() => add.mutate()} disabled={!newItem.trim()} className="p-2 bg-primary text-primary-foreground rounded-md disabled:opacity-50"><Plus size={16} /></button>
      </div>
      {isLoading && <div className="text-muted-foreground text-sm">加载中...</div>}
      <div className="space-y-1.5">
        {todos.map((t) => (
          <div key={t.id} className="flex items-center gap-3 border rounded-lg px-4 py-2.5 bg-card">
            <button onClick={() => toggle.mutate({ id: t.id, done: !t.done })} className={`p-0.5 rounded border ${t.done ? 'bg-primary border-primary text-primary-foreground' : 'border-border'}`}><Check size={12} /></button>
            <span className={`flex-1 text-sm ${t.done ? 'line-through text-muted-foreground' : ''}`}>{t.title}</span>
            <button onClick={() => remove.mutate(t.id)} className="p-1 hover:text-destructive transition-colors"><Trash2 size={14} /></button>
          </div>
        ))}
      </div>
    </div>
  )
}
