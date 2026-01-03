import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { papersApi } from '@/api/papers';

export function usePapers() {
    return useQuery({
        queryKey: ['papers'],
        queryFn: papersApi.getAll,
    });
}

export function usePaper(id: number) {
    return useQuery({
        queryKey: ['papers', id],
        queryFn: () => papersApi.getById(id),
        enabled: !!id,
    });
}

export function usePaperStats() {
    return useQuery({
        queryKey: ['papers', 'stats'],
        queryFn: papersApi.getStats,
    });
}

export function useCreatePaper() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (data: { paperName: string; questionIds: string[] }) =>
            papersApi.create(data.paperName, data.questionIds),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['papers'] });
        },
    });
}

export function useDeletePaper() {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: papersApi.delete,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['papers'] });
        },
    });
}

export function useDownloadLink(id: number) {
    return useQuery({
        queryKey: ['papers', id, 'download'],
        queryFn: () => papersApi.getDownloadLink(id),
        enabled: false, // Manual trigger usually
    });
}
