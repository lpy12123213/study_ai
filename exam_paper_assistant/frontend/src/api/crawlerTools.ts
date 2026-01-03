import { client } from "./client";
import type {
  AvailableFiltersRequest,
  AvailableFiltersResponse,
  ComposeBlueprintRequest,
  ComposeBlueprintResponse,
} from "@/types";

export const crawlerToolsApi = {
  getAvailableFilters: async (request: AvailableFiltersRequest) => {
    const response = await client.post<AvailableFiltersResponse>(
      "/available-filters",
      request,
    );
    return response.data;
  },

  composeBlueprint: async (request: ComposeBlueprintRequest) => {
    const response = await client.post<ComposeBlueprintResponse>(
      "/compose-blueprint",
      request,
    );
    return response.data;
  },
};

