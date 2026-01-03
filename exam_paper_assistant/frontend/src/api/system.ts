import { client } from "./client";
import type { HealthResponse, RuntimeConfig } from "@/types";

export const systemApi = {
  health: async () => {
    const response = await client.get<HealthResponse>("/health");
    return response.data;
  },
  config: async () => {
    const response = await client.get<RuntimeConfig>("/config");
    return response.data;
  },
};

