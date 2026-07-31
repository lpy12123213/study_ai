import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { systemApi } from "@/shared/api/system";
import { useUiStore } from "@/stores/ui";
import { GlobalSearch } from "../global-search";

vi.mock("@/shared/api/system", () => ({
  systemApi: {
    search: vi.fn(),
  },
}));

function renderSearch() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <GlobalSearch />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe("GlobalSearch", () => {
  const searchMock = vi.mocked(systemApi.search);

  beforeEach(() => {
    vi.useFakeTimers();
    searchMock.mockResolvedValue({ query: "", results: [], count: 0 });
    useUiStore.setState({ searchOpen: true });
  });

  afterEach(() => {
    useUiStore.setState({ searchOpen: false });
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it("在 80ms 后发起搜索并把查询取消信号传给 API", async () => {
    renderSearch();

    fireEvent.change(screen.getByPlaceholderText("搜索对话、试卷、资料、题目…"), {
      target: { value: "函数" },
    });
    await advance(79);
    expect(searchMock).not.toHaveBeenCalled();

    await advance(1);
    expect(searchMock).toHaveBeenCalledOnce();
    expect(searchMock.mock.calls[0][0]).toBe("函数");
    expect(searchMock.mock.calls[0][3]).toBeInstanceOf(AbortSignal);
  });

  it("输入新关键词时取消仍在执行的旧搜索", async () => {
    searchMock.mockImplementation(
      (_query, _types, _limit, signal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("aborted", "AbortError")),
            { once: true },
          );
          if (signal?.aborted) {
            reject(new DOMException("aborted", "AbortError"));
          }
        }),
    );
    renderSearch();
    const input = screen.getByPlaceholderText("搜索对话、试卷、资料、题目…");

    fireEvent.change(input, { target: { value: "函数" } });
    await advance(80);
    const firstSignal = searchMock.mock.calls[0][3];
    expect(firstSignal?.aborted).toBe(false);

    fireEvent.change(input, { target: { value: "函数图像" } });
    await advance(80);

    expect(searchMock).toHaveBeenCalledTimes(2);
    expect(firstSignal?.aborted).toBe(true);
  });
});
