/** Chat feature API（自 lib/api/chat.ts 迁入，架构 Phase 5）。 */
import { apiFetch } from "@/shared/api/http-client";
import { streamPost, type StreamHandlers } from "@/lib/sse";
import type { ChatMessage, Conversation } from "@/shared/api/types";

export const conversationsApi = {
  list: (limit = 50) => apiFetch<Conversation[]>("/api/conversations", { query: { limit } }),
  create: (title = "新对话") => apiFetch<{ id: number; title: string }>("/api/conversations", { method: "POST", body: { title } }),
  remove: (id: number) => apiFetch(`/api/conversations/${id}`, { method: "DELETE" }),
  rename: (id: number, title: string) =>
    apiFetch(`/api/conversations/${id}`, { method: "PATCH", body: { title } }),
  messages: (id: number, opts?: { limit?: number; beforeId?: number; includeTrace?: boolean; includeToolContent?: boolean }) =>
    apiFetch<{ conversation: Conversation; messages: ChatMessage[]; paging?: any }>(
      `/api/conversations/${id}/messages`,
      {
        query: {
          limit: opts?.limit ?? 100,
          before_id: opts?.beforeId,
          // 默认视图会过滤 tool 消息与带 tool_calls 的 assistant 消息，需要工具历史时显式开启
          include_trace: opts?.includeTrace,
          include_tool_content: opts?.includeToolContent,
        },
      },
    ),
  fork: (id: number, messageId: number, title?: string) =>
    apiFetch<Conversation>(`/api/conversations/${id}/fork`, {
      method: "POST",
      body: { message_id: messageId, ...(title ? { title } : {}) },
    }),
  /**
   * 请求取消该会话进行中的生成（服务端取消契约）。
   * accepted=true 只表示信号已发出；实际停止以流内 `cancelled` 事件为准。
   */
  cancelGeneration: (id: number) =>
    apiFetch<{ success: boolean; accepted: boolean }>(`/api/chat/${id}/cancel`, { method: "POST" }),
};

export interface ChatSendPayload {
  conversation_id: number;
  message: string;
  subject?: string;
  model?: string;
  sub_model?: string;
  /** 结构化语义确认 intent（如 confirm_create_paper）：服务端据此绕过确认词匹配。 */
  intent?: string;
}

/**
 * 发送对话消息（SSE 流）。
 * 事件（扁平）：stream_start / text_delta / thinking_delta / iteration / assistant /
 * tool_start / tool_result / assistant_final / cancelled / error，结尾 `data: [DONE]`。
 */
export function sendChatMessage(payload: ChatSendPayload, handlers: StreamHandlers) {
  return streamPost("/api/chat", payload, handlers);
}
