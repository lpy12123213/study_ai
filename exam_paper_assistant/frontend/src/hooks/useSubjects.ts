import { useQuery } from "@tanstack/react-query";
import { subjectsApi } from "@/api/subjects";

export function useSubjects() {
  return useQuery({
    queryKey: ["subjects"],
    queryFn: subjectsApi.getAll,
    staleTime: 60 * 60 * 1000,
  });
}

