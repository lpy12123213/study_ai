import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { COMPOSER_MODES } from "../../model/composer-modes";
import { PromptComposer } from "../prompt-composer";

function Harness(props: Partial<React.ComponentProps<typeof PromptComposer>>) {
  const [value, setValue] = useState("");
  return <PromptComposer value={value} onChange={setValue} onSubmit={() => {}} {...props} />;
}

describe("PromptComposer", () => {
  it("输入后 Enter 提交，Shift+Enter 不提交", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const box = screen.getByRole("textbox");
    await user.type(box, "hello{Shift>}{Enter}{/Shift}world");
    expect(onSubmit).not.toHaveBeenCalled();
    await user.type(box, "{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("空内容时发送按钮禁用", () => {
    render(<Harness />);
    expect(screen.getByRole("button", { name: /发送/ })).toBeDisabled();
  });

  it("sending 时显示停止接收并回调 onStop", async () => {
    const user = userEvent.setup();
    const onStop = vi.fn();
    render(<Harness sending onStop={onStop} />);
    expect(screen.queryByRole("button", { name: /发送/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /停止接收/ }));
    expect(onStop).toHaveBeenCalledTimes(1);
    // 停止语义：文案不得声称服务端已取消
    expect(screen.queryByText(/停止任务|已取消/)).not.toBeInTheDocument();
  });

  it("leftSlot 渲染在底部左侧", () => {
    render(<Harness leftSlot={<span>学科槽位</span>} />);
    expect(screen.getByText("学科槽位")).toBeInTheDocument();
  });

  it("空态模式前缀均为提示策略（不伪装独立模型）", () => {
    expect(COMPOSER_MODES.map((m) => m.label)).toEqual(["讲清概念", "陪我推导", "生成练习", "整理笔记"]);
    for (const m of COMPOSER_MODES) {
      expect(m.prefix.endsWith("：")).toBe(true);
    }
  });
});
