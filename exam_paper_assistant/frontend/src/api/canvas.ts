import { client } from "./client";
import type {
  CanvasBoardDetail,
  CanvasBoardSummary,
  CanvasPickedQuestion,
  CanvasBoardVersion,
  CanvasBoardVersionDetail,
} from "@/types";

export type ListCanvasBoardsParams = {
  limit?: number;
  q?: string;
};

export type CreateCanvasBoardPayload = {
  title?: string;
  subject?: string;
  snapshot?: Record<string, unknown>;
};

export type UpdateCanvasBoardPayload = {
  title?: string;
  subject?: string;
  snapshot?: Record<string, unknown>;
  expected_revision?: number;
};

export type PickQuestionsPayload = {
  requirement: string;
  subject?: string;
  edu_level?: string;
  count?: number;
  model?: string;
  limit?: number;
  max_pages?: number;
};

export const canvasApi = {
  listBoards: async (params?: ListCanvasBoardsParams) => {
    const response = await client.get<{ success: boolean; boards: CanvasBoardSummary[] }>(
      "/canvas/boards",
      { params },
    );
    return response.data;
  },

  createBoard: async (payload: CreateCanvasBoardPayload) => {
    const response = await client.post<{ success: boolean; board: CanvasBoardSummary }>(
      "/canvas/boards",
      payload,
    );
    return response.data;
  },

  getBoard: async (boardId: number) => {
    const response = await client.get<{ success: boolean; board: CanvasBoardDetail }>(
      `/canvas/boards/${boardId}`,
    );
    return response.data;
  },

  updateBoard: async (boardId: number, payload: UpdateCanvasBoardPayload) => {
    const response = await client.put<
      | { success: true; board: CanvasBoardDetail }
      | { success: false; conflict: true; server_board: CanvasBoardDetail }
    >(`/canvas/boards/${boardId}`, payload);
    return response.data;
  },

  listVersions: async (boardId: number, params?: { limit?: number }) => {
    const response = await client.get<{ success: boolean; versions: CanvasBoardVersion[] }>(
      `/canvas/boards/${boardId}/versions`,
      { params },
    );
    return response.data;
  },

  createVersion: async (boardId: number) => {
    const response = await client.post<{
      success: boolean;
      version: CanvasBoardVersion;
      versions: CanvasBoardVersion[];
    }>(`/canvas/boards/${boardId}/versions`);
    return response.data;
  },

  getVersion: async (boardId: number, versionId: number) => {
    const response = await client.get<{ success: boolean; version: CanvasBoardVersionDetail }>(
      `/canvas/boards/${boardId}/versions/${versionId}`,
    );
    return response.data;
  },

  pickQuestions: async (boardId: number, payload: PickQuestionsPayload) => {
    const response = await client.post<{
      success: boolean;
      subject: string;
      edu_level: string;
      requirement: string;
      candidate_count: number;
      selected_ids: string[];
      questions: CanvasPickedQuestion[];
      selection: Array<Record<string, unknown>>;
    }>(`/canvas/boards/${boardId}/pick-questions`, payload);
    return response.data;
  },
};
