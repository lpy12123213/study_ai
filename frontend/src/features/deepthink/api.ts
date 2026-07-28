/** DeepThink feature API（自 lib/api/misc.ts 迁入，架构 Phase 5）。 */
import { streamPost, type StreamHandlers } from "@/lib/sse";

/** DeepThink 深度解题（POST 即流）：search_start → node_* → best_path → answer_start/answer_delta → done。 */
export function solveDeepThink(
  payload: { question: string; subject?: string; image_url?: string },
  handlers: StreamHandlers,
) {
  return streamPost("/api/deepthink", payload, handlers);
}
