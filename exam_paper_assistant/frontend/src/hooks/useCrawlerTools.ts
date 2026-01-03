import { useMutation, useQuery } from "@tanstack/react-query";
import { crawlerToolsApi } from "@/api/crawlerTools";
import type { AvailableFiltersRequest, ComposeBlueprintRequest } from "@/types";

export function useAvailableFilters(request: AvailableFiltersRequest, enabled = true) {
  return useQuery({
    queryKey: ["crawler_tools", "available_filters", request.subject, request.edu_level],
    queryFn: () => crawlerToolsApi.getAvailableFilters(request),
    enabled: enabled && !!request.subject,
  });
}

export function useComposeBlueprint() {
  return useMutation({
    mutationFn: (request: ComposeBlueprintRequest) =>
      crawlerToolsApi.composeBlueprint(request),
  });
}

