import { client } from './client';
import type { Conversation, ConversationDetail } from '@/types';

export const chatApi = {
    getAllConversations: async () => {
        const response = await client.get<Conversation[]>('/conversations');
        return response.data;
    },

    createConversation: async (title: string) => {
        const response = await client.post<Conversation>('/conversations', { title });
        return response.data;
    },

    getMessages: async (id: number) => {
        const response = await client.get<ConversationDetail>(`/conversations/${id}/messages`);
        return response.data;
    },

    updateConversationTitle: async (id: number, title: string) => {
        const response = await client.patch<{ success: boolean; conversation: Conversation }>(
            `/conversations/${id}`,
            { title }
        );
        return response.data;
    },

    deleteConversation: async (id: number) => {
        await client.delete(`/conversations/${id}`);
    },
};
