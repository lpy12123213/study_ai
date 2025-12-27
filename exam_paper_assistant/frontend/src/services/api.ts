import axios from 'axios';

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '');

const api = axios.create({
  baseURL: API_BASE,
});

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

export interface Subject {
  name: string;
  short_name: string;
  bank_id: number;
  edu_id: number;
}

type SubjectsResponse = { subjects: Subject[] };

// ============ 学科 API ============

export const getSubjects = async (): Promise<Subject[]> => {
  const { data } = await api.get<SubjectsResponse>('/api/subjects');
  return data.subjects;
};

// ============ 对话 API ============

export const getConversations = async (): Promise<Conversation[]> => {
  const { data } = await api.get<Conversation[]>('/api/conversations');
  return data;
};

export const createConversation = async (title?: string): Promise<{ id: number; title: string }> => {
  const { data } = await api.post<{ id: number; title: string }>('/api/conversations', { title });
  return data;
};

export const deleteConversation = async (id: number): Promise<void> => {
  await api.delete(`/api/conversations/${id}`);
};

export const getConversationMessages = async (
  id: number
): Promise<{ conversation: Conversation; messages: Message[] }> => {
  const { data } = await api.get<{ conversation: Conversation; messages: Message[] }>(`/api/conversations/${id}/messages`);
  return data;
};

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

async function* readSseLines(reader: ReadableStreamDefaultReader<Uint8Array>): AsyncGenerator<string, void, unknown> {
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
  const response = await fetch(`${API_BASE}/api/chat`, {
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

// ============ 试卷相关类型 ============

export interface Question {
  question_id: string;
  type?: string;
  difficulty?: string;
  source_url?: string;
}

export interface Paper {
  paper_id: number;
  paper_name: string;
  question_count: number;
  created_at: string;
}

export interface PaperDetail extends Paper {
  questions: Question[];
  analysis?: {
    difficulty_score: number;
    radar_data: Array<{ subject: string; A: number; fullMark: number }>;
    ai_comment: string;
  };
}

export interface DownloadLinkResponse {
  success: boolean;
  paper_name: string;
  question_count: number;
  question_ids: string[];
  question_links: string[];
  instructions: string[];
}

// ============ 试卷 API ============

export const getPapers = async (): Promise<Paper[]> => {
  const { data } = await api.get<Paper[]>('/api/papers');
  return data;
};

export const getPaperDetail = async (id: number): Promise<PaperDetail> => {
  const { data } = await api.get<PaperDetail>(`/api/papers/${id}`);
  return data;
};

export const deletePaper = async (id: number): Promise<void> => {
  await api.delete(`/api/papers/${id}`);
};

export const getDownloadLink = async (id: number): Promise<DownloadLinkResponse> => {
  const { data } = await api.get<DownloadLinkResponse>(`/api/papers/${id}/download-link`);
  return data;
};
