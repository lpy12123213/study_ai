import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { Node } from '@xyflow/react';
import { cn } from '@/lib/utils';
import { User, Bot, GitFork } from 'lucide-react';
import { Button } from '@/components/ui/button';

export interface MessageNodeData extends Record<string, unknown> {
    role: 'user' | 'assistant';
    content: string;
    isStreaming?: boolean;
    onFork?: () => void;
}

export type MessageNode = Node<MessageNodeData, 'message'>;

interface MessageNodeProps {
    data: MessageNodeData;
    selected?: boolean;
}

function MessageNodeComponent({ data, selected }: MessageNodeProps) {
    const isUser = data.role === 'user';

    return (
        <div
            className={cn(
                'relative min-w-[280px] max-w-[400px] rounded-xl border shadow-md transition-all',
                isUser
                    ? 'bg-primary text-primary-foreground border-primary/50'
                    : 'bg-card text-card-foreground border-border',
                selected && 'ring-2 ring-ring ring-offset-2 ring-offset-background'
            )}
        >
            {/* Header */}
            <div className="flex items-center gap-2 px-4 py-2 border-b border-inherit/20">
                {isUser ? (
                    <User className="h-4 w-4" />
                ) : (
                    <Bot className="h-4 w-4" />
                )}
                <span className="text-xs font-medium">
                    {isUser ? 'You' : 'AI Assistant'}
                </span>
                {!isUser && data.onFork && (
                    <Button
                        variant="ghost"
                        size="icon"
                        className="ml-auto h-6 w-6 opacity-60 hover:opacity-100"
                        onClick={data.onFork}
                        title="Fork conversation"
                    >
                        <GitFork className="h-3 w-3" />
                    </Button>
                )}
            </div>

            {/* Content */}
            <div className="px-4 py-3 text-sm whitespace-pre-wrap">
                {data.content}
                {data.isStreaming && (
                    <span className="inline-block w-2 h-4 ml-1 bg-current animate-pulse" />
                )}
            </div>

            {/* Handles for connections */}
            <Handle
                type="target"
                position={Position.Top}
                className="!bg-muted-foreground !w-3 !h-3"
            />
            <Handle
                type="source"
                position={Position.Bottom}
                className="!bg-muted-foreground !w-3 !h-3"
            />
        </div>
    );
}

export default memo(MessageNodeComponent);
