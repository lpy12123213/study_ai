import { Send, Loader2, Sparkles } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import MessageBubble from './MessageBubble';
import type { Message, ToolCall, ToolResult } from '@/api';

interface Props {
  messages: Message[];
  toolResults: ToolResult[];
  onSend: (message: string) => void;
  loading: boolean;
  streamingContent: string;
  currentToolCalls: ToolCall[];
}

export default function ChatArea({
  messages,
  toolResults,
  onSend,
  loading,
  streamingContent,
  currentToolCalls
}: Props) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent, toolResults]);

  // 自动调整输入框高度
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  const handleSubmit = () => {
    if (!input.trim() || loading) return;
    onSend(input.trim());
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // 合并消息和流式内容
  const displayMessages = [...messages];

  return (
    <div className="flex-1 flex flex-col h-full relative">
      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6 custom-scrollbar pb-32">
        {displayMessages.length === 0 && !loading ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.5 }}
            className="h-full flex flex-col items-center justify-center text-slate-500"
          >
            <div className="w-24 h-24 bg-gradient-to-br from-primary/20 to-accent/20 rounded-3xl flex items-center justify-center mb-6 shadow-xl shadow-primary/10">
              <Sparkles className="w-12 h-12 text-primary" />
            </div>
            <div className="text-2xl font-bold mb-3 text-white">智能组卷助手</div>
            <div className="text-sm text-center max-w-md text-slate-400 leading-relaxed">
              告诉我您需要什么样的试卷，我会帮您搜索题目并组卷。<br />
              <span className="inline-block mt-2 p-2 bg-slate-800/50 rounded-lg text-xs border border-white/5">
                例如："帮我出一份高中数学函数专题测试，10道选择题，难度中等"
              </span>
            </div>
          </motion.div>
        ) : (
          <AnimatePresence initial={false}>
            {displayMessages.map((msg, idx) => {
              // 跳过工具消息，它们会在助手消息中显示
              if (msg.role === 'tool') return null;

              return (
                <motion.div
                  key={msg.id || idx}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                >
                  <MessageBubble
                    role={msg.role}
                    content={msg.content}
                    toolCalls={msg.tool_calls}
                    toolResults={toolResults.filter(tr =>
                      msg.tool_calls?.some(tc => tc.id === tr.tool_call_id) ?? false
                    )}
                  />
                </motion.div>
              );
            })}

            {/* 流式响应 */}
            {loading && (streamingContent || currentToolCalls.length > 0) && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <MessageBubble
                  role="assistant"
                  content={streamingContent}
                  toolCalls={currentToolCalls}
                  toolResults={toolResults}
                  isStreaming={true}
                />
              </motion.div>
            )}

            {/* 加载指示器 */}
            {loading && !streamingContent && currentToolCalls.length === 0 && (
              <motion.div
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                className="flex gap-3"
              >
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary to-primary-hover flex items-center justify-center shadow-lg shadow-primary/20">
                  <Loader2 className="w-4 h-4 text-white animate-spin" />
                </div>
                <div className="bg-slate-800/80 backdrop-blur rounded-2xl rounded-tl-sm p-4 border border-white/5 shadow-lg">
                  <div className="flex gap-1.5">
                    <span className="w-2 h-2 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-primary/60 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* 输入区 */}
      <div className="absolute bottom-0 left-0 right-0 p-6 bg-gradient-to-t from-slate-950 via-slate-950/90 to-transparent z-10">
        <div className="max-w-4xl mx-auto relative">
          <div className="absolute inset-0 bg-gradient-to-r from-primary/20 via-accent/20 to-primary/20 rounded-2xl blur-xl opacity-20 pointer-events-none" />
          <div className="relative flex gap-3 items-end bg-slate-900/80 backdrop-blur-xl border border-white/10 rounded-2xl p-2 shadow-2xl shadow-black/50 transition-all focus-within:border-primary/50 focus-within:bg-slate-900/90 focus-within:shadow-primary/10">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="描述您的组卷需求... (Enter发送, Shift+Enter换行)"
              disabled={loading}
              rows={1}
              className="flex-1 bg-transparent border-none px-4 py-3 text-sm resize-none focus:ring-0 text-slate-200 placeholder:text-slate-500 max-h-32 custom-scrollbar"
            />
            <button
              onClick={handleSubmit}
              disabled={loading || !input.trim()}
              className="p-3 bg-gradient-to-br from-primary to-primary-hover hover:from-primary-hover hover:to-primary text-white disabled:opacity-50 disabled:cursor-not-allowed rounded-xl transition-all shadow-lg shadow-primary/20 hover:shadow-primary/40 hover:-translate-y-0.5 active:translate-y-0"
            >
              {loading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </button>
          </div>
          <div className="text-center mt-2">
            <p className="text-[10px] text-slate-600">AI 生成内容仅供参考，请以官方题库为准</p>
          </div>
        </div>
      </div>
    </div>
  );
}
