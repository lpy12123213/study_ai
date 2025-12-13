import { ShoppingBasket, Trash2, FilePlus } from 'lucide-react';
import { useState } from 'react';

interface Props {
  ids: string[];
  onRemove: (id: string) => void;
  onClear: () => void;
  onCreate: (name: string) => void;
  creating: boolean;
}

export default function Basket({ ids, onRemove, onClear, onCreate, creating }: Props) {
  const [name, setName] = useState('');

  return (
    <div className="bg-card rounded-2xl p-5 border border-white/5 shadow-lg h-fit sticky top-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <ShoppingBasket className="w-5 h-5 text-primary" />
          试题篮
          <span className="text-sm font-normal text-slate-400 bg-slate-800 px-2 py-0.5 rounded-full">{ids.length}</span>
        </h2>
        {ids.length > 0 && (
          <button onClick={onClear} className="text-xs text-danger hover:text-red-400">清空</button>
        )}
      </div>

      <div className="min-h-[100px] max-h-[300px] overflow-y-auto space-y-2 mb-4 pr-1 custom-scrollbar">
        {ids.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            暂无题号<br/>请在左侧搜索添加
          </div>
        ) : (
          ids.map((id, idx) => (
            <div key={id} className="flex items-center justify-between bg-slate-900/50 p-2.5 rounded-lg border border-white/5 text-sm">
              <span className="font-mono text-slate-300">#{idx + 1} {id}</span>
              <button onClick={() => onRemove(id)} className="text-slate-500 hover:text-danger transition-colors">
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          ))
        )}
      </div>

      <div className="pt-4 border-t border-white/5 space-y-3">
        <input 
          value={name}
          onChange={e => setName(e.target.value)}
          className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary/50"
          placeholder="试卷名称..."
        />
        <button 
          onClick={() => { onCreate(name); setName(''); }}
          disabled={creating || ids.length === 0 || !name}
          className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed text-slate-900 font-semibold py-2.5 rounded-xl transition-all"
        >
          <FilePlus className="w-4 h-4" />
          {creating ? '生成中...' : '生成试卷'}
        </button>
      </div>
    </div>
  );
}
