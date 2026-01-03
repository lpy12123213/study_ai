import { useQuery } from "@tanstack/react-query";
import { systemApi } from "@/api/system";

export function useHealth() {
  return useQuery({
    queryKey: ["system", "health"],
    queryFn: systemApi.health,
    refetchOnWindowFocus: false,
  });
}

export function useRuntimeConfig() {
  return useQuery({
    queryKey: ["system", "config"],
    queryFn: systemApi.config,
    refetchOnWindowFocus: false,
  });
}

