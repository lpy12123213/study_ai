import { CheckCircle, Loader2, AlertCircle, ChevronDown, Terminal } from 'lucide-react';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

interface ToolCallProps {
  toolName: string;
  arguments: Record<string, unknown>;
  result?: unknown;
  status: 'pending' | 'running' | 'completed' | 'error';
  iteration?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

const toolNameMap: Record<string, string> = {
  search_questions: '搜索题目',
  create_paper: '创建试卷',
  get_papers: '获取试卷列表',
  get_question_detail: '获取题目详情',
  batch_get_question_details: '批量获取题目详情'
};

const toolIconColors: Record<string, string> = {
  search_questions: 'text-blue-400',
  create_paper: 'text-emerald-400',
  get_papers: 'text-violet-400',
  get_question_detail: 'text-orange-400',
  batch_get_question_details: 'text-cyan-400'
};

export default function ToolCallCard({ toolName, arguments: args, result, status, iteration }: ToolCallProps) {
  const [expanded, setExpanded] = useState(false);

  const displayName = toolNameMap[toolName] || toolName;
  const iconColor = toolIconColors[toolName] || 'text-primary';

  const argRows: JSX.Element[] = Object.entries(args).map(([key, value]) => {
    const displayValue = typeof value === 'object' ? JSON.stringify(value) : String(value);
    return (
      <div key={key} className="flex gap-2">
        <span className="text-primary-light">{key}:</span>
        <span className="text-slate-400 break-all">{displayValue}</span>
      </div>
    );
  });

  const getStatusIcon = () => {
    switch (status) {
      case 'running':
        return <Loader2 className="w-3.5 h-3.5 text-accent animate-spin" />;
      case 'completed':
        return <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />;
      case 'error':
        return <AlertCircle className="w-3.5 h-3.5 text-red-400" />;
      default:
        return <Loader2 className="w-3.5 h-3.5 text-slate-500" />;
    }
  };

  const getStatusText = () => {
    switch (status) {
      case 'running': return '执行中...';
      case 'completed': return getResultSummary();
      case 'error': {
        if (isRecord(result) && typeof result.error === 'string') return result.error;
        return '执行失败';
      }
      default: return '等待执行';
    }
  };

  const getResultSummary = () => {
    if (!result) return '完成';

    const rec = isRecord(result) ? result : null;

    if (toolName === 'search_questions' && rec) {
      const questions = Array.isArray(rec.questions) ? rec.questions : [];
      const count =
        questions.length ||
        (typeof rec.count === 'number' ? rec.count : typeof rec.total === 'number' ? rec.total : 0);
      return `找到 ${count} 道题目`;
    }

    if (toolName === 'create_paper') return '试卷已创建';

    if (toolName === 'get_papers' && rec) {
      const papers = Array.isArray(rec.papers) ? rec.papers : [];
      const count = papers.length || (typeof rec.count === 'number' ? rec.count : 0);
      return `共 ${count} 份试卷`;
    }

    if (toolName === 'batch_get_question_details' && rec) {
      const results = Array.isArray(rec.results) ? rec.results : [];
      return `获取 ${results.length} 题详情`;
    }

    return '完成';
  };

  return (
    <div className="bg-slate-900/40 border border-white/5 rounded-xl overflow-hidden backdrop-blur-sm transition-all hover:bg-slate-900/60 hover:border-white/10 group">
      {/* Header */}
      <div
        className="flex items-center gap-3 p-3 cursor-pointer select-none"
        onClick={() => setExpanded(!expanded)}
      >
        <div className={`p-1.5 rounded-lg bg-slate-800/50 border border-white/5 ${iconColor}`}>
          <Terminal className="w-3.5 h-3.5" />
        </div>

        <div className="flex-1 flex items-center gap-2 min-w-0">
          <span className="text-xs font-medium text-slate-300 truncate">{displayName}</span>
          {iteration && iteration > 1 && (
            <span className="px-1.5 py-0.5 text-[10px] bg-primary/10 border border-primary/20 text-primary-light rounded-full">
              R{iteration}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2 pl-2 border-l border-white/5">
          {getStatusIcon()}
          <span className={`text-[10px] ${status === 'error' ? 'text-red-400' : 'text-slate-500'} truncate max-w-[100px]`}>
            {getStatusText()}
          </span>
          <motion.div
            animate={{ rotate: expanded ? 180 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronDown className="w-3.5 h-3.5 text-slate-500 group-hover:text-slate-300" />
          </motion.div>
        </div>
      </div>

      {/* Expanded Content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
          >
            <div className="border-t border-white/5 p-3 space-y-3 bg-slate-950/30">
              {/* Arguments */}
              <div>
                <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 font-semibold">Input</div>
                <div className="bg-slate-950/50 rounded-lg p-2.5 text-xs font-mono text-slate-300 border border-white/5 overflow-x-auto">
                  {argRows}
                </div>
              </div>

              {/* Result */}
              {status === 'completed' && result != null && (
                <div>
                  <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5 font-semibold">Output</div>
                  <div className="bg-slate-950/50 rounded-lg p-2.5 text-xs font-mono text-slate-300 border border-white/5 max-h-40 overflow-y-auto custom-scrollbar">
                    {toolName === 'search_questions' && isRecord(result) && Array.isArray(result.questions) ? (
                      <div className="space-y-1">
                        {(result.questions as unknown[]).slice(0, 5).map((q, i) => {
                          const qRec = isRecord(q) ? q : {};
                          const qid = typeof qRec.question_id === 'string' ? qRec.question_id : 'N/A';
                          const diff = typeof qRec.difficulty === 'string' ? qRec.difficulty : '未知';
                          return (
                            <div key={i} className="flex gap-2">
                              <span className="text-accent">#{i + 1}</span>
                              <span className="text-slate-400">{qid}</span>
                              <span className="text-slate-500">[{diff}]</span>
                            </div>
                          );
                        })}
                        {(result.questions as unknown[]).length > 5 && (
                          <div className="text-slate-500 italic pl-1">
                            ... 还有 {(result.questions as unknown[]).length - 5} 道题目
                          </div>
                        )}
                      </div>
                    ) : (
                      <pre className="whitespace-pre-wrap break-all">
                        {JSON.stringify(result, null, 2)}
                      </pre>
                    )}
                  </div>
                </div>
              )}

              {/* Error */}
              {status === 'error' && isRecord(result) && typeof result.error === 'string' && (
                <div className="text-xs text-red-300 bg-red-500/10 border border-red-500/20 p-2.5 rounded-lg">
                  {result.error}
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
