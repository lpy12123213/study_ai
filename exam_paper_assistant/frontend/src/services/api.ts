import axios from 'axios';

const API_BASE = '';

// ============ 对话相关类型 ============

export interface Conversation {
    id: number;
    title: string;
    created_at: string;
    updated_at: string;
}

export interface Message {
    id: number;
    role: 'user' | 'assistant' | 'tool';
    content: string;
    tool_calls?: any[];
    tool_call_id?: string;
    created_at: string;
}

export interface ToolResult {
    tool_call_id: string;
    tool_name: string;
    arguments?: any;
    result?: any;
    status: 'pending' | 'running' | 'completed' | 'error';
    iteration?: number;  // 多轮工具调用的轮次
}

export interface Subject {
    name: string;
    short_name: string;
    bank_id: number;
    edu_id: number;
}

// ============ 学科 API ============

export const getSubjects = async (): Promise<Subject[]> => {
    const response = await axios.get(`${API_BASE}/api/subjects`);
    return response.data.subjects;
};

// ============ 对话 API ============

export const getConversations = async (): Promise<Conversation[]> => {
    const response = await axios.get(`${API_BASE}/api/conversations`);
    return response.data;
};

export const createConversation = async (title?: string): Promise<{ id: number; title: string }> => {
    const response = await axios.post(`${API_BASE}/api/conversations`, { title });
    return response.data;
};

export const deleteConversation = async (id: number): Promise<void> => {
    await axios.delete(`${API_BASE}/api/conversations/${id}`);
};

export const getConversationMessages = async (id: number): Promise<{ conversation: Conversation; messages: Message[] }> => {
    const response = await axios.get(`${API_BASE}/api/conversations/${id}/messages`);
    return response.data;
};

export const sendChatMessage = async (
    conversationId: number,
    message: string,
    onChunk: (chunk: any) => void,
    subject: string = '高中数学'
): Promise<void> => {
    console.log('[API] Sending chat message:', { conversationId, message, subject });

    const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            conversation_id: conversationId,
            message: message,
            subject: subject,
        }),
    });

    console.log('[API] Response status:', response.status);

    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
        throw new Error('No response body');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let chunkCount = 0;

    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            console.log('[API] Stream done, total chunks:', chunkCount);
            break;
        }

        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (line.startsWith('data: ')) {
                const data = line.slice(6);
                if (data === '[DONE]') {
                    console.log('[API] Received [DONE]');
                    return;
                }
                try {
                    const parsed = JSON.parse(data);
                    console.log('[API] Chunk received:', parsed.type);
                    chunkCount++;
                    onChunk(parsed);
                } catch (e) {
                    console.error('Failed to parse SSE data:', e, 'Line:', line);
                }
            }
        }
    }
};

// ============ 旧的试卷相关类型（保留兼容） ============

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

// ============ 试卷 API（保留） ============

export const getPapers = async (): Promise<Paper[]> => {
    const response = await axios.get(`${API_BASE}/api/papers`);
    return response.data;
};

export const getPaperDetail = async (id: number): Promise<PaperDetail> => {
    const response = await axios.get(`${API_BASE}/api/papers/${id}`);
    return response.data;
};

export const deletePaper = async (id: number): Promise<void> => {
    await axios.delete(`${API_BASE}/api/papers/${id}`);
};

export const getDownloadLink = async (id: number): Promise<any> => {
    const response = await axios.get(`${API_BASE}/api/papers/${id}/download-link`);
    return response.data;
};
