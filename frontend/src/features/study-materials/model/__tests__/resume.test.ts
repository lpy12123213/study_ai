import { describe, expect, it } from "vitest";

import { resolveResumeAfterSeq } from "../resume";

describe("resolveResumeAfterSeq", () => {
  it("同一任务续播：用当前投影进度", () => {
    expect(
      resolveResumeAfterSeq({
        currentTaskId: "t1",
        currentLastSeq: 120,
        targetTaskId: "t1",
        persistedLastSeq: 80,
      }),
    ).toBe(120);
  });

  it("重新进入（投影为空）：用持久化进度而不是从 0 全量回放", () => {
    expect(
      resolveResumeAfterSeq({
        currentTaskId: null,
        currentLastSeq: 0,
        targetTaskId: "t1",
        persistedLastSeq: 3500,
      }),
    ).toBe(3500);
  });

  it("切换到不同任务：用持久化进度", () => {
    expect(
      resolveResumeAfterSeq({
        currentTaskId: "t2",
        currentLastSeq: 999,
        targetTaskId: "t1",
        persistedLastSeq: 42,
      }),
    ).toBe(42);
  });

  it("无持久化进度时回退到 0", () => {
    expect(
      resolveResumeAfterSeq({
        currentTaskId: null,
        currentLastSeq: 0,
        targetTaskId: "t1",
      }),
    ).toBe(0);
  });

  it("负数进度钳到 0", () => {
    expect(
      resolveResumeAfterSeq({
        currentTaskId: "t1",
        currentLastSeq: -5,
        targetTaskId: "t1",
      }),
    ).toBe(0);
  });
});
