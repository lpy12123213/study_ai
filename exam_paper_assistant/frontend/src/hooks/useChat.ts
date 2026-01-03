import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { chatApi } from '@/api/chat';

export function useConversations() {
    return useQuery({
        queryKey: ['conversations'],
        queryFn: chatApi.getAllConversations,
    });
}

export function useConversationMessages(id: number | null) {
    return useQuery({
        queryKey: ['conversations', id, 'messages'],
        queryFn: () => chatApi.getMessages(id!),
        enabled: !!id,
    });
}

export function useCreateConversation() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: chatApi.createConversation,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['conversations'] });
        },
    });
}

export function useDeleteConversation() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: chatApi.deleteConversation,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['conversations'] });
        },
    });
}

export function useUpdateConversationTitle() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, title }: { id: number; title: string }) =>
            chatApi.updateConversationTitle(id, title),
        onSuccess: (_, vars) => {
            queryClient.invalidateQueries({ queryKey: ['conversations'] });
            queryClient.invalidateQueries({ queryKey: ['conversations', vars.id, 'messages'] });
        },
    });
}
