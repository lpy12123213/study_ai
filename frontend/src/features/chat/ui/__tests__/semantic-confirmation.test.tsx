import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PromptComposer } from "../prompt-composer";
import { SemanticConfirmation } from "../semantic-confirmation";

describe("SemanticConfirmation", () => {
  it("三个快捷操作分别回调（普通消息语义，不是系统审批）", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    const onRevise = vi.fn();
    const onViewCandidates = vi.fn();
    render(
      <SemanticConfirmation onConfirm={onConfirm} onRevise={onRevise} onViewCandidates={onViewCandidates} />,
    );

    await user.click(screen.getByRole("button", { name: /确认并创建/ }));
    await user.click(screen.getByRole("button", { name: /修改方案/ }));
    await user.click(screen.getByRole("button", { name: /先看候选题/ }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onRevise).toHaveBeenCalledTimes(1);
    expect(onViewCandidates).toHaveBeenCalledTimes(1);
  });

  it("disabled 时全部按钮不可用", () => {
    render(
      <SemanticConfirmation onConfirm={() => {}} onRevise={() => {}} onViewCandidates={() => {}} disabled />,
    );
    for (const name of [/确认并创建/, /修改方案/, /先看候选题/]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });
});

describe("PromptComposer stopLabel", () => {
  it("默认停止文案为「停止接收」；具备取消契约的调用方可传入「停止任务」", () => {
    const { rerender } = render(
      <PromptComposer value="" onChange={() => {}} onSubmit={() => {}} sending onStop={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /停止接收/ })).toBeInTheDocument();

    rerender(
      <PromptComposer
        value=""
        onChange={() => {}}
        onSubmit={() => {}}
        sending
        onStop={() => {}}
        stopLabel="停止任务"
        stopTitle="请求服务端停止本轮生成"
      />,
    );
    expect(screen.getByRole("button", { name: /停止任务/ })).toBeInTheDocument();
  });
});
