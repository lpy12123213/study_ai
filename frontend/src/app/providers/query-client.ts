import { QueryClient } from "@tanstack/react-query";

/** 应用级 QueryClient 配置（架构 Phase 1 自 main.tsx 提取，默认值不变）。 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1,
        refetchOnWindowFocus: false,
        staleTime: 15_000,
      },
    },
  });
}

export const queryClient = createQueryClient();
