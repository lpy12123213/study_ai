import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatPage } from "@/pages/chat";

/** 页面级冒烟：新装配的 ChatPage（投影 + 时间线）在空会话下可渲染。 */

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

function renderChat(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/chat/:id" element={<ChatPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ChatPage 冒烟", () => {
  it("无会话时渲染欢迎空态与输入舱", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: unknown) => {
        const url = String(input);
        if (url.startsWith("/api/conversations")) return jsonResponse([]);
        return jsonResponse({});
      }),
    );
    renderChat("/chat");
    expect(await screen.findByText("开始新的学习对话")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Enter 发送/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /新建对话/ })).toBeInTheDocument();
  });

  it("有会话时渲染历史消息与停止接收按钮状态", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: unknown) => {
        const url = String(input);
        if (url.startsWith("/api/conversations/7/messages")) {
          return jsonResponse({
            conversation: { id: 7, title: "数列讨论" },
            messages: [
              { id: 1, role: "user", content: "讲讲数列", created_at: "2026-07-26T00:00:00Z" },
              { id: 2, role: "assistant", content: "数列是按一定次序排列的一列数。", created_at: "2026-07-26T00:00:01Z" },
            ],
          });
        }
        if (url.startsWith("/api/conversations")) {
          return jsonResponse([
            { id: 7, title: "数列讨论", created_at: "2026-07-26T00:00:00Z", updated_at: "2026-07-26T00:00:00Z" },
          ]);
        }
        return jsonResponse({});
      }),
    );
    renderChat("/chat/7");
    expect(await screen.findByText("数列是按一定次序排列的一列数。")).toBeInTheDocument();
    // 非生成中：显示「发送」而非「停止接收」
    expect(screen.getByRole("button", { name: /发送/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /停止接收/ })).not.toBeInTheDocument();
  });

  it("携带 ?message= 锚点时历史加载后滚动并短暂高亮目标消息", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: unknown) => {
        const url = String(input);
        if (url.startsWith("/api/conversations/7/messages")) {
          return jsonResponse({
            conversation: { id: 7, title: "数列讨论" },
            messages: [
              { id: 1, role: "user", content: "讲讲数列", created_at: "2026-07-26T00:00:00Z" },
              { id: 2, role: "assistant", content: "数列是按一定次序排列的一列数。", created_at: "2026-07-26T00:00:01Z" },
            ],
          });
        }
        if (url.startsWith("/api/conversations")) {
          return jsonResponse([
            { id: 7, title: "数列讨论", created_at: "2026-07-26T00:00:00Z", updated_at: "2026-07-26T00:00:00Z" },
          ]);
        }
        return jsonResponse({});
      }),
    );
    renderChat("/chat/7?message=2");
    expect(await screen.findByText("数列是按一定次序排列的一列数。")).toBeInTheDocument();

    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    const target = document.querySelector('[data-message-id="2"]');
    expect(target).not.toBeNull();
    expect(target?.getAttribute("data-message-id")).toBe("2");
    // 高亮类短暂出现后由定时器清除
    expect(target?.className).toContain("ring-primary");

    Element.prototype.scrollIntoView = undefined as unknown as typeof Element.prototype.scrollIntoView;
  });
});
