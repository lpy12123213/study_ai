import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { canvasApi } from "@/api/canvas";

export function useCanvasBoards(params?: { q?: string; limit?: number }) {
  return useQuery({
    queryKey: ["canvas", "boards", params],
    queryFn: () => canvasApi.listBoards(params),
  });
}

export function useCanvasBoard(boardId: number | null) {
  return useQuery({
    queryKey: ["canvas", "boards", boardId],
    queryFn: async () => {
      if (!boardId) throw new Error("boardId_required");
      const data = await canvasApi.getBoard(boardId);
      return data.board;
    },
    enabled: Boolean(boardId),
  });
}

export function useCreateCanvasBoard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: canvasApi.createBoard,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["canvas", "boards"] });
    },
  });
}

export function useUpdateCanvasBoard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: { boardId: number; payload: Parameters<typeof canvasApi.updateBoard>[1] }) =>
      canvasApi.updateBoard(args.boardId, args.payload),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["canvas", "boards", variables.boardId] });
      queryClient.invalidateQueries({ queryKey: ["canvas", "boards"] });
    },
  });
}

export function useCanvasVersions(boardId: number | null, params?: { limit?: number }) {
  return useQuery({
    queryKey: ["canvas", "boards", boardId, "versions", params],
    queryFn: async () => {
      if (!boardId) throw new Error("boardId_required");
      const data = await canvasApi.listVersions(boardId, params);
      return data.versions;
    },
    enabled: Boolean(boardId),
  });
}

export function useCreateCanvasVersion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: canvasApi.createVersion,
    onSuccess: (_data, boardId) => {
      queryClient.invalidateQueries({ queryKey: ["canvas", "boards", boardId, "versions"] });
    },
  });
}

