import { client } from './client';
import type { Paper, PaperResponse, DownloadLinkResponse } from '@/types';

export const papersApi = {
    getStats: async () => {
        // This is a derived stats call or needs a new endpoint
        // For now, we can fetch all papers and count them locally if count is small
        // Or just return mock data if backend doesn't support stats
        const papers = await papersApi.getAll();
        return {
            totalPapers: papers.length,
            recentPapers: papers.slice(0, 5),
        };
    },

    getAll: async () => {
        const response = await client.get<Paper[]>('/papers');
        return response.data;
    },

    getById: async (id: number) => {
        const response = await client.get<Paper>(`/papers/${id}`);
        return response.data;
    },

    create: async (paperName: string, questionIds: string[]) => {
        const response = await client.post<PaperResponse>('/papers', {
            paper_name: paperName,
            question_ids: questionIds,
        });
        return response.data;
    },

    delete: async (id: number) => {
        await client.delete(`/papers/${id}`);
    },

    getDownloadLink: async (id: number) => {
        const response = await client.get<DownloadLinkResponse>(`/papers/${id}/download-link`);
        return response.data;
    },
};
