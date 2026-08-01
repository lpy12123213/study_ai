/**
 * DeepThink 页面诚实停止语义冒烟：
 * - 运行中按钮文案为「停止接收」（不宣称后端已停止）；
 * - 提交后把 {taskId,lastSeq,question,subject} 持久化到 localStorage；
 * - 点击停止接收时调用 tasksApi.cancel(taskId)。
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { submitDeepThink } from "@/features/deepthink/api";
import { tasksApi } from "@/features/task-center/api";
import { DeepthinkPage } from "@/pages/deepthink";

vi.mock("@/features/deepthink/api", () => ({
  submitDeepThink: vi.fn(),
}));

vi.mock("@/features/task-center/api", () => ({
  tasksApi: {
    get: vi.fn(),
    cancel: vi.fn(),
  },
}));

const ACTIVE_RUN_KEY = "study-ai:deepthink:active-run";

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  closed = false;
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close() {
    this.closed = true;
  }
}

function renderPage(initialPath = "/deepthink") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path="/deepthink" element={<DeepthinkPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("DeepthinkPage 停止语义", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    localStorage.clear();
    vi.mocked(submitDeepThink).mockResolvedValue({ success: true, taskId: "deepthink-test-1" });
    vi.mocked(tasksApi.cancel).mockResolvedValue({ success: true });
    vi.mocked(tasksApi.get).mockResolvedValue({ id: "deepthink-test-1", task_type: "deepthink", status: "running", progress: 0 });
  });

  it("停止按钮文案为「停止接收」；停止时调用取消 API 并持久化 taskId", async () => {
    renderPage();

    // 输入题目并提交
    fireEvent.change(screen.getByLabelText("题目"), { target: { value: "求极限" } });
    fireEvent.click(screen.getByRole("button", { name: "开始解题" }));

    // 提交后进入运行视图：显示「停止接收」而非「停止」
    expect(await screen.findByRole("button", { name: "停止接收" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^停止$/ })).not.toBeInTheDocument();

    // 持久化写入 taskId
    await waitFor(() => {
      const persisted = JSON.parse(localStorage.getItem(ACTIVE_RUN_KEY) ?? "{}");
      expect(persisted.taskId).toBe("deepthink-test-1");
      expect(persisted.question).toBe("求极限");
    });

    // 点击停止接收：尽力调用服务端取消 API
    fireEvent.click(screen.getByRole("button", { name: "停止接收" }));
    await waitFor(() => expect(tasksApi.cancel).toHaveBeenCalledWith("deepthink-test-1"));

    // 停止接收后进入终态：徽标「已停止接收」，本地持久化清除
    expect(await screen.findByText("已停止接收")).toBeInTheDocument();
    expect(localStorage.getItem(ACTIVE_RUN_KEY)).toBeNull();
  });
});
