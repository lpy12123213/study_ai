import { Search } from 'lucide-react';
import { useState } from 'react';

interface Props {
  onSearch: (kw: string, diff: string, type: string, limit: number) => void;
  loading: boolean;
}

export default function SearchSection({ onSearch, loading }: Props) {
  const [kw, setKw] = useState('');
  const [diff, setDiff] = useState('');
  const [type, setType] = useState('');
  const [limit, setLimit] = useState(10);

  return (
    <div className="bg-card rounded-2xl p-5 border border-white/5 shadow-lg">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Search className="w-5 h-5 text-primary" />
        检索题目
      </h2>
      <div className="space-y-4">
        <div>
          <label className="block text-xs text-slate-400 mb-1.5">关键词</label>
          <input 
            value={kw}
            onChange={e => setKw(e.target.value)}
            className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-4 py-2.5 text-sm focus:outline-none focus:border-primary/50 transition-colors placeholder:text-slate-600"
            placeholder="输入关键词，如：函数、不等式..."
          />
        </div>
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">难度</label>
            <select 
              value={diff}
              onChange={e => setDiff(e.target.value)}
              className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary/50"
            >
              <option value="">不限</option>
              <option value="简单">简单</option>
              <option value="中等">中等</option>
              <option value="困难">困难</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">题型</label>
            <input 
              value={type}
              onChange={e => setType(e.target.value)}
              className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary/50"
              placeholder="如：选择题"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">数量</label>
            <input 
              type="number"
              min="1" max="50"
              value={limit}
              onChange={e => setLimit(parseInt(e.target.value))}
              className="w-full bg-slate-900/50 border border-white/10 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary/50"
            />
          </div>
        </div>
        <button 
          onClick={() => onSearch(kw, diff, type, limit)}
          disabled={loading || !kw}
          className="w-full bg-primary hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed text-slate-900 font-semibold py-3 rounded-xl transition-all shadow-lg shadow-primary/20 active:scale-[0.98]"
        >
          {loading ? '搜索中...' : '开始搜索'}
        </button>
      </div>
    </div>
  );
}
