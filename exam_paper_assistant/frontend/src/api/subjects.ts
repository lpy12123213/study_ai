import { client } from "./client";
import type { Subject } from "@/types";

export const subjectsApi = {
  getAll: async () => {
    const response = await client.get<{ subjects: Subject[] }>("/subjects");
    return response.data.subjects;
  },
};

