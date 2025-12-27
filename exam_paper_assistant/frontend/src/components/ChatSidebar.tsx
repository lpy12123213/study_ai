import { MessageSquarePlus, Trash2, MessageCircle, FileText } from 'lucide-react';
import { useState } from 'react';
import PaperHistory from './PaperHistory';
import type { Conversation } from '@/api';

interface Props {
  conversations: Conversation[];
  currentId: number | null;
  onSelect: (id: number) => void;
  onCreate: () => void;
  onDelete: (id: number) => void;
  loading: boolean;
}

type TabType = 'conversations' | 'papers';

export default function ChatSidebar({
  conversations,
  currentId,
  onSelect,
  onCreate,
  onDelete,
  loading
}: Props) {
  const [activeTab, setActiveTab] = useState<TabType>('conversations');

  return (
    <div className="flex flex-col h-full w-full">
      {/* 标签切换 */}
      <div className="p-2 border-b border-white/5">
        <div className="flex gap-1 bg-slate-800/50 rounded-lg p-1">
          <button
            onClick={() => setActiveTab('conversations')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-md text-xs font-medium transition-all ${activeTab === 'conversations'
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-slate-300'
              }`}
          >
            <MessageCircle className="w-3.5 h-3.5" />
            对话
          </button>
          <button
            onClick={() => setActiveTab('papers')}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 px-3 rounded-md text-xs font-medium transition-all ${activeTab === 'papers'
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-slate-300'
              }`}
          >
            <FileText className="w-3.5 h-3.5" />
            试卷
          </button>
        </div>
      </div>

      {activeTab === 'conversations' ? (
        <>
          {/* 新建对话按钮 */}
          <div className="p-4 border-b border-white/5">
            <button
              onClick={onCreate}
              className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark text-slate-900 font-semibold py-3 rounded-xl transition-all"
            >
              <MessageSquarePlus className="w-5 h-5" />
              新建对话
            </button>
          </div>

          {/* 对话列表 */}
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {loading ? (
              <div className="text-center py-8 text-slate-500 text-sm">
                加载中...
              </div>
            ) : conversations.length === 0 ? (
              <div className="text-center py-8 text-slate-500 text-sm">
                暂无对话记录<br />点击上方按钮开始
              </div>
            ) : (
              conversations.map((conv) => (
                <div
                  key={conv.id}
                  onClick={() => onSelect(conv.id)}
                  className={`group flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all ${currentId === conv.id
                      ? 'bg-primary/20 border border-primary/30'
                      : 'hover:bg-slate-800/50 border border-transparent'
                    }`}
                >
                  <MessageCircle className={`w-4 h-4 shrink-0 ${currentId === conv.id ? 'text-primary' : 'text-slate-500'
                    }`} />
                  <div className="flex-1 min-w-0">
                    <div className={`text-sm truncate ${currentId === conv.id ? 'text-white' : 'text-slate-300'
                      }`}>
                      {conv.title}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">
                      {new Date(conv.updated_at).toLocaleDateString()}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(conv.id);
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-red-500/20 rounded-lg transition-all"
                  >
                    <Trash2 className="w-4 h-4 text-red-400" />
                  </button>
                </div>
              ))
            )}
          </div>

          {/* 底部信息 */}
          <div className="p-4 border-t border-white/5 text-xs text-slate-500 text-center">
            AI 智能组卷助手
          </div>
        </>
      ) : (
        <PaperHistory />
      )}
    </div>
  );
}
