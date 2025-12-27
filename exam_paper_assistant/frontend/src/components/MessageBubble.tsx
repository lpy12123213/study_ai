import { User, Sparkles } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import ToolCallCard from './ToolCallCard';
import type { ToolCall, ToolResult } from '@/api';

interface MessageProps {
  role: 'user' | 'assistant' | 'tool';
  content: string;
  toolCalls?: ToolCall[] | null;
  toolResults?: ToolResult[];
  isStreaming?: boolean;
}

export default function MessageBubble({
  role,
  content,
  toolCalls,
  toolResults,
  isStreaming
}: MessageProps) {
  const isUser = role === 'user';

  const getToolResult = (toolCallId: string) => {
    return toolResults?.find(tr => tr.tool_call_id === toolCallId);
  };

  return (
    <div className={`flex gap-4 ${isUser ? 'flex-row-reverse' : ''} group`}>
      {/* Avatar */}
      <div className={`w-9 h-9 rounded-xl flex items-center justify-center shrink-0 shadow-lg ${isUser
        ? 'bg-gradient-to-br from-primary to-primary-hover shadow-primary/20'
        : 'bg-slate-800/80 border border-white/5 shadow-black/20'
        }`}>
        {isUser ? (
          <User className="w-5 h-5 text-white" />
        ) : (
          <Sparkles className="w-5 h-5 text-primary" />
        )}
      </div>

      {/* Content */}
      <div className={`flex-1 max-w-[85%] ${isUser ? 'items-end flex flex-col' : ''}`}>
        <div
          className={`relative px-5 py-4 rounded-2xl shadow-md transition-all duration-200 ${isUser
            ? 'bg-gradient-to-br from-primary to-primary-hover text-white rounded-tr-sm shadow-primary/10'
            : 'bg-slate-800/50 backdrop-blur-sm border border-white/5 text-slate-200 rounded-tl-sm shadow-black/10 group-hover:bg-slate-800/70'
            }`}
        >
          {content ? (
            <div className={`markdown-content prose prose-invert max-w-none ${isUser ? 'prose-p:text-white prose-headings:text-white prose-strong:text-white' : ''
              }`}>
              <ReactMarkdown
                components={{
                  p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
                  code: ({ className, children }) => {
                    const isInline = !className;
                    return isInline ? (
                      <code className={`px-1.5 py-0.5 rounded text-xs font-mono ${isUser ? 'bg-white/20 text-white' : 'bg-slate-950/50 text-accent'
                        }`}>
                        {children}
                      </code>
                    ) : (
                      <code className="block bg-slate-950/50 p-3 rounded-lg text-xs font-mono overflow-x-auto border border-white/5 my-2">
                        {children}
                      </code>
                    );
                  },
                  pre: ({ children }) => <pre className="bg-transparent p-0 my-0">{children}</pre>,
                  a: ({ href, children }) => (
                    <a href={href} target="_blank" rel="noopener noreferrer" className={`${isUser ? 'text-white underline decoration-white/50' : 'text-accent hover:text-accent-hover underline decoration-accent/30'
                      }`}>
                      {children}
                    </a>
                  ),
                }}
              >
                {content}
              </ReactMarkdown>
            </div>
          ) : (isStreaming && !toolCalls ? (
            <div className="flex items-center gap-2 text-slate-400 text-sm">
              <span className="w-1.5 h-1.5 bg-slate-400 rounded-full animate-pulse" />
              思考中...
            </div>
          ) : null)}

          {isStreaming && content && (
            <span className="inline-block w-1.5 h-4 ml-1 align-middle bg-current animate-pulse" />
          )}
        </div>

        {/* Tool Calls */}
        {toolCalls && toolCalls.length > 0 && (
          <div className="mt-3 space-y-2 w-full max-w-2xl">
            {toolCalls.map((tc) => {
              const result = getToolResult(tc.id);
              let args: Record<string, unknown> = {};
              try {
                const parsed: unknown = JSON.parse(tc.function.arguments) as unknown;
                if (typeof parsed === 'object' && parsed !== null) {
                  args = parsed as Record<string, unknown>;
                }
              } catch {
                // ignore invalid JSON in tool arguments
              }

              return (
                <ToolCallCard
                  key={tc.id}
                  toolName={tc.function.name}
                  arguments={args}
                  result={result?.result}
                  status={result?.status || 'pending'}
                  iteration={result?.iteration}
                />
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
