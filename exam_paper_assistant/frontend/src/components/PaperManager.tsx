import { FileText, Eye, Download, Trash2, RefreshCw } from 'lucide-react';
import { Paper } from '../services/api';

interface Props {
  papers: Paper[];
  loading: boolean;
  onRefresh: () => void;
  onView: (id: number) => void;
  onDownload: (id: number) => void;
  onDelete: (id: number) => void;
}

export default function PaperManager({ papers, loading, onRefresh, onView, onDownload, onDelete }: Props) {
  return (
    <div className="bg-card rounded-2xl p-5 border border-white/5 shadow-lg mt-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <FileText className="w-5 h-5 text-primary" />
          我的试卷
        </h2>
        <button onClick={onRefresh} className="p-2 hover:bg-slate-800 rounded-lg transition-colors">
          <RefreshCw className={`w-4 h-4 text-slate-400 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="space-y-3">
        {papers.length === 0 ? (
            <div className="text-center py-8 text-slate-500 text-sm">
                暂无试卷
            </div>
        ) : (
            papers.map((p) => (
            <div key={p.paper_id} className="bg-slate-900/30 p-4 rounded-xl border border-white/5 flex items-center justify-between hover:bg-slate-900/50 transition-colors">
                <div>
                <div className="font-medium text-slate-200">{p.paper_name}</div>
                <div className="text-xs text-slate-500 mt-1">
                    {p.question_count} 题 · {new Date(p.created_at).toLocaleString()}
                </div>
                </div>
                <div className="flex items-center gap-2">
                <button onClick={() => onView(p.paper_id)} className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors" title="详情">
                    <Eye className="w-4 h-4" />
                </button>
                <button onClick={() => onDownload(p.paper_id)} className="p-2 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors" title="下载链接">
                    <Download className="w-4 h-4" />
                </button>
                <button onClick={() => onDelete(p.paper_id)} className="p-2 text-slate-400 hover:text-danger hover:bg-danger/10 rounded-lg transition-colors" title="删除">
                    <Trash2 className="w-4 h-4" />
                </button>
                </div>
            </div>
            ))
        )}
      </div>
    </div>
  );
}
