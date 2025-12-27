import { apiUrl, axiosClient } from './http';

// ============ 对话相关类型 ============

export interface Conversation {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ToolCall {
  id: string;
  function: {
    name: string;
    arguments: string;
  };
  type?: string;
  [key: string]: unknown;
}

export interface Message {
  id: number;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  tool_calls?: ToolCall[] | null;
  tool_call_id?: string;
  created_at: string;
}

export interface ToolResult {
  tool_call_id: string;
  tool_name: string;
  arguments?: unknown;
  result?: unknown;
  status: 'pending' | 'running' | 'completed' | 'error';
  iteration?: number; // 多轮工具调用的轮次
}

// ============ 对话 API ============

export const getConversations = async (): Promise<Conversation[]> => {
  const { data } = await axiosClient.get<Conversation[]>('/api/conversations');
  return data;
};

export const createConversation = async (title?: string): Promise<{ id: number; title: string }> => {
  const { data } = await axiosClient.post<{ id: number; title: string }>('/api/conversations', { title });
  return data;
};

export const deleteConversation = async (id: number): Promise<void> => {
  await axiosClient.delete(`/api/conversations/${id}`);
};

export const getConversationMessages = async (
  id: number
): Promise<{ conversation: Conversation; messages: Message[] }> => {
  const { data } = await axiosClient.get<{ conversation: Conversation; messages: Message[] }>(
    `/api/conversations/${id}/messages`
  );
  return data;
};

// ============ Chat SSE Stream ============

export type ChatStreamChunk =
  | {
      type: 'iteration';
      round: number;
      message: string;
    }
  | {
      type: 'assistant';
      content: string;
      tool_calls?: ToolCall[];
      iteration?: number;
    }
  | {
      type: 'tool_start';
      tool_call_id: string;
      tool_name: string;
      arguments: Record<string, unknown>;
      iteration?: number;
    }
  | {
      type: 'tool_result';
      tool_call_id: string;
      tool_name: string;
      result: unknown;
      iteration?: number;
    }
  | {
      type: 'stream_start';
      iteration?: number;
    }
  | {
      type: 'text_delta';
      content: string;
    }
  | {
      type: 'assistant_final';
      content: string;
      total_iterations?: number;
      max_reached?: boolean;
    }
  | {
      type: 'error';
      content: string;
    };

async function* readSseLines(
  reader: ReadableStreamDefaultReader<Uint8Array>
): AsyncGenerator<string, void, unknown> {
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) return;

    buffer += decoder.decode(value, { stream: true });

    // Handle both LF and CRLF; keep partial line in buffer.
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';

    for (const rawLine of lines) {
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
      yield line;
    }
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isChatStreamChunk(value: unknown): value is ChatStreamChunk {
  if (!isRecord(value)) return false;
  return typeof value.type === 'string';
}

export const sendChatMessage = async (
  conversationId: number,
  message: string,
  onChunk: (chunk: ChatStreamChunk) => void,
  subject: string = '高中数学'
): Promise<void> => {
  const response = await fetch(apiUrl('/api/chat'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      subject,
    }),
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  for await (const line of readSseLines(reader)) {
    if (!line.startsWith('data: ')) continue;

    const data = line.slice(6);
    if (data === '[DONE]') return;

    try {
      const parsed: unknown = JSON.parse(data) as unknown;
      if (isChatStreamChunk(parsed)) {
        onChunk(parsed);
      }
    } catch (e) {
      console.error('Failed to parse SSE data:', e, 'Line:', line);
    }
  }
};

