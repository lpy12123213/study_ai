import { FileText, Trash2, ExternalLink, Loader2 } from 'lucide-react';
import { useState, useEffect } from 'react';
import { getPapers, getPaperDetail, deletePaper, getDownloadLink, Paper, PaperDetail } from '../services/api';

export default function PaperHistory() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [paperDetail, setPaperDetail] = useState<PaperDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 加载试卷列表
  const loadPapers = async () => {
    setLoading(true);
    try {
      const data = await getPapers();
      setPapers(data);
    } catch (error) {
      console.error('Failed to load papers:', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPapers();
  }, []);

  // 展开/收起试卷详情
  const toggleExpand = async (paperId: number) => {
    if (expandedId === paperId) {
      setExpandedId(null);
      setPaperDetail(null);
      return;
    }

    setExpandedId(paperId);
    setDetailLoading(true);
    try {
      const detail = await getPaperDetail(paperId);
      setPaperDetail(detail);
    } catch (error) {
      console.error('Failed to load paper detail:', error);
    } finally {
      setDetailLoading(false);
    }
  };

  // 删除试卷
  const handleDelete = async (paperId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('确定删除这份试卷吗？')) return;

    try {
      await deletePaper(paperId);
      setPapers(papers.filter(p => p.paper_id !== paperId));
      if (expandedId === paperId) {
        setExpandedId(null);
        setPaperDetail(null);
      }
    } catch (error) {
      console.error('Failed to delete paper:', error);
      alert('删除失败');
    }
  };

  // 获取下载链接
  const handleDownload = async (paperId: number, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const data = await getDownloadLink(paperId);
      // 打开第一个题目链接作为示例
      if (data.question_links && data.question_links.length > 0) {
        window.open(data.question_links[0], '_blank');
      }
    } catch (error) {
      console.error('Failed to get download link:', error);
    }
  };

  // 格式化日期
  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('zh-CN', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  return (
    <div className="h-full flex flex-col">
      {/* 头部 */}
      <div className="p-4 border-b border-white/5 bg-white/5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-white flex items-center gap-2">
            <FileText className="w-4 h-4 text-primary" />
            组卷历史
          </h2>
          <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-white/5">{papers.length}</span>
        </div>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-y-auto custom-scrollbar">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="w-5 h-5 text-primary animate-spin" />
          </div>
        ) : papers.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-slate-500">
            <FileText className="w-8 h-8 mb-2 opacity-30" />
            <span className="text-xs">暂无试卷</span>
          </div>
        ) : (
          <div className="p-2 space-y-2">
            {papers.map((paper) => (
              <div key={paper.paper_id} className="rounded-xl overflow-hidden border border-white/5 bg-slate-900/30 transition-all hover:bg-slate-900/50">
                {/* 试卷项 */}
                <div
                  onClick={() => toggleExpand(paper.paper_id)}
                  className={`p-3 cursor-pointer transition-all ${expandedId === paper.paper_id
                    ? 'bg-slate-800/50'
                    : ''
                    }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className={`text-sm truncate font-medium transition-colors ${expandedId === paper.paper_id ? 'text-primary' : 'text-slate-200'
                        }`}>
                        {paper.paper_name}
                      </div>
                      <div className="flex items-center gap-2 mt-1.5 text-[10px] text-slate-500">
                        <span className="bg-slate-800 px-1.5 py-0.5 rounded">{paper.question_count} 题</span>
                        <span>{formatDate(paper.created_at)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={(e) => handleDownload(paper.paper_id, e)}
                        className="p-1.5 text-slate-400 hover:text-primary hover:bg-primary/10 rounded-lg transition-colors"
                        title="查看题目"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                      </button>
                      <button
                        onClick={(e) => handleDelete(paper.paper_id, e)}
                        className="p-1.5 text-slate-400 hover:text-red-400 hover:bg-red-400/10 rounded-lg transition-colors"
                        title="删除"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>

                {/* 展开详情 */}
                {expandedId === paper.paper_id && (
                  <div className="bg-black/20 border-t border-white/5 p-3 animate-slide-up">
                    {detailLoading ? (
                      <div className="flex items-center justify-center py-4">
                        <Loader2 className="w-4 h-4 text-primary animate-spin" />
                      </div>
                    ) : paperDetail ? (
                      <div className="space-y-3">
                        {/* 分析结果 */}
                        {paperDetail.analysis && (
                          <div className="bg-slate-800/50 rounded-lg p-3 space-y-2 border border-white/5">
                            <div className="flex items-center justify-between text-xs">
                              <span className="text-slate-400">难度系数</span>
                              <span className={`font-bold ${paperDetail.analysis.difficulty_score > 0.7 ? 'text-red-400' :
                                paperDetail.analysis.difficulty_score > 0.4 ? 'text-yellow-400' :
                                  'text-emerald-400'
                                }`}>
                                {(paperDetail.analysis.difficulty_score * 100).toFixed(0)}%
                              </span>
                            </div>
                            {paperDetail.analysis.ai_comment && (
                              <p className="text-xs text-slate-400 leading-relaxed border-t border-white/5 pt-2 mt-2">
                                {paperDetail.analysis.ai_comment}
                              </p>
                            )}
                          </div>
                        )}

                        {/* 题目列表 */}
                        <div>
                          <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-2 font-semibold">题目列表</div>
                          <div className="space-y-1 max-h-40 overflow-y-auto custom-scrollbar pr-1">
                            {paperDetail.questions.map((q, idx) => (
                              <a
                                key={q.question_id}
                                href={`https://zujuan.xkw.com/11q${q.question_id}.html`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="flex items-center gap-2 p-2 bg-slate-800/30 rounded hover:bg-primary/10 hover:border-primary/20 border border-transparent transition-all group"
                              >
                                <span className="text-xs text-slate-500 w-5 font-mono">{idx + 1}.</span>
                                <span className="text-xs text-slate-300 flex-1 truncate group-hover:text-primary transition-colors">
                                  {q.question_id}
                                </span>
                                {q.type && (
                                  <span className="text-[10px] px-1.5 py-0.5 bg-slate-800 rounded text-slate-400">{q.type}</span>
                                )}
                                <ExternalLink className="w-3 h-3 text-slate-600 group-hover:text-primary opacity-0 group-hover:opacity-100 transition-all" />
                              </a>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className="text-center text-slate-500 text-sm py-2">
                        加载失败
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
