import { Plus, ExternalLink } from 'lucide-react';
import type { Question } from '@/api';

interface Props {
  questions: Question[];
  onAdd: (q: Question) => void;
  basketIds: string[];
}

export default function QuestionList({ questions, onAdd, basketIds }: Props) {
  if (questions.length === 0) return null;

  return (
    <div className="mt-4 grid gap-3">
      {questions.map((q) => {
        const isAdded = basketIds.includes(q.question_id);
        return (
          <div key={q.question_id} className="bg-card/50 p-4 rounded-xl border border-white/5 flex items-center justify-between group hover:border-white/10 transition-colors">
            <div className="overflow-hidden">
              <div className="font-mono text-sm text-primary mb-1">ID: {q.question_id}</div>
              <div className="text-xs text-slate-400 flex gap-3">
                <span>{q.type || '未知题型'}</span>
                <span>{q.difficulty || '未知难度'}</span>
                <a href={q.source_url} target="_blank" rel="noreferrer" className="text-slate-500 hover:text-primary flex items-center gap-1">
                  原题 <ExternalLink className="w-3 h-3" />
                </a>
              </div>
            </div>
            <button
              onClick={() => onAdd(q)}
              disabled={isAdded}
              className={`p-2 rounded-lg transition-all ${
                isAdded 
                ? 'bg-slate-800 text-slate-500 cursor-not-allowed' 
                : 'bg-primary/10 text-primary hover:bg-primary hover:text-slate-900'
              }`}
            >
              <Plus className="w-5 h-5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
