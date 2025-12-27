import { axiosClient } from './http';

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

export const getPapers = async (): Promise<Paper[]> => {
  const { data } = await axiosClient.get<Paper[]>('/api/papers');
  return data;
};

export const getPaperDetail = async (id: number): Promise<PaperDetail> => {
  const { data } = await axiosClient.get<PaperDetail>(`/api/papers/${id}`);
  return data;
};

export const deletePaper = async (id: number): Promise<void> => {
  await axiosClient.delete(`/api/papers/${id}`);
};

export const getDownloadLink = async (id: number): Promise<DownloadLinkResponse> => {
  const { data } = await axiosClient.get<DownloadLinkResponse>(`/api/papers/${id}/download-link`);
  return data;
};

