import { describe, expect, it } from "vitest";

import {
  deepthinkProjectionReducer,
  initialDeepthinkProjection,
  type DeepthinkProjection,
} from "@/features/deepthink/model/projection";
import type { TaskEvent } from "@/shared/api/types";

function run(actions: Parameters<typeof deepthinkProjectionReducer>[1][], state?: DeepthinkProjection) {
  return actions.reduce((s, a) => deepthinkProjectionReducer(s, a), state ?? initialDeepthinkProjection());
}

const ev = (type: string, data: Record<string, unknown> = {}): TaskEvent => ({ type, data }) as TaskEvent;

describe("deepthinkProjectionReducer", () => {
  it("start 清空运行区并进入 running", () => {
    const dirty = run([{ type: "event", ev: ev("answer_delta", { content: "x" }) }], {
      ...initialDeepthinkProjection(),
      phase: "running",
    });
    const s = run([{ type: "start" }], dirty);
    expect(s.phase).toBe("running");
    expect(s.answer).toBe("");
    expect(s.nodes).toHaveLength(0);
  });

  it("node_generated 追加节点且按 id 去重", () => {
    const s = run([
      { type: "start" },
      { type: "event", ev: ev("node_generated", { node: { id: "n1", depth: 0, thought: "t" } }) },
      { type: "event", ev: ev("node_generated", { node: { id: "n1", depth: 0, thought: "t" } }) },
    ]);
    expect(s.nodes).toHaveLength(1);
    expect(s.nodes[0].status).toBe("pending");
  });

  it("node_evaluated / node_pruned 按 nodeId 打补丁", () => {
    const s = run([
      { type: "start" },
      { type: "event", ev: ev("node_generated", { node: { id: "n1" } }) },
      { type: "event", ev: ev("node_evaluated", { nodeId: "n1", score: 8.5, issues: ["a"] }) },
      { type: "event", ev: ev("node_pruned", { nodeId: "n1", reason: "低分" }) },
    ]);
    expect(s.nodes[0].status).toBe("pruned");
    expect(s.nodes[0].score).toBe(8.5);
    expect(s.nodes[0].issues).toEqual(["a"]);
    expect(s.nodes[0].pruneReason).toBe("低分");
  });

  it("answer_delta / thinking_delta 累积文本", () => {
    const s = run([
      { type: "start" },
      { type: "event", ev: ev("answer_delta", { content: "解：" }) },
      { type: "event", ev: ev("answer_delta", { content: "答案" }) },
      { type: "event", ev: ev("thinking_delta", { content: "想想" }) },
    ]);
    expect(s.answer).toBe("解：答案");
    expect(s.reasoning).toBe("想想");
  });

  it("done 事件置终态并记录统计", () => {
    const s = run([{ type: "start" }, { type: "event", ev: ev("done", { elapsed: 3.2, bestScore: 9 }) }]);
    expect(s.phase).toBe("done");
    expect(s.doneInfo).toEqual({ elapsed: 3.2, bestScore: 9, totalNodes: undefined });
  });

  it("error 事件把 llm_not_configured 映射为友好文案", () => {
    const s = run([{ type: "start" }, { type: "event", ev: ev("error", { message: "llm_not_configured" }) }]);
    expect(s.phase).toBe("error");
    expect(s.errorMsg).toContain("未配置 LLM");
  });

  it("stopped 保留内容并进入 done；stream_done 仅在 running 时兜底", () => {
    let s = run([{ type: "start" }, { type: "event", ev: ev("answer_delta", { content: "半截" }) }]);
    s = run([{ type: "stopped" }], s);
    expect(s.phase).toBe("done");
    expect(s.stopped).toBe(true);
    expect(s.answer).toBe("半截");
    // 终态后 stream_done / 残留事件不再改变投影
    expect(run([{ type: "stream_done" }], s).phase).toBe("done");
    expect(run([{ type: "event", ev: ev("answer_delta", { content: "x" }) }], s).answer).toBe("半截");
    // idle 时 stream_done 不兜底
    expect(run([{ type: "stream_done" }]).phase).toBe("idle");
  });

  it("clear 回到初始态；back_to_edit 只切回 idle", () => {
    let s = run([{ type: "start" }, { type: "event", ev: ev("answer_delta", { content: "x" }) }]);
    expect(run([{ type: "clear" }], s)).toEqual(initialDeepthinkProjection());
    s = run([{ type: "back_to_edit" }], s);
    expect(s.phase).toBe("idle");
    expect(s.answer).toBe("x");
  });
});
