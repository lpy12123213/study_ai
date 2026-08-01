import { act, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { systemApi } from "@/shared/api/system";
import type { GlobalSearchResult } from "@/shared/api/types";
import { useUiStore } from "@/stores/ui";
import { GlobalSearch } from "../global-search";

vi.mock("@/shared/api/system", () => ({
  systemApi: {
    search: vi.fn(),
  },
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderSearch() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <GlobalSearch />
        <LocationProbe />
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

  it("match_count>1 渲染「N 条匹配」徽标，单个命中的实体不显示", async () => {
    vi.useRealTimers();
    searchMock.mockResolvedValue({
      query: "数列",
      results: [
        {
          type: "conversation",
          title: "数列讨论",
          snippet: "…",
          score: 1,
          conversation_id: 5,
          message_id: 12,
          match_count: 6,
        },
        {
          type: "paper",
          title: "函数专题卷",
          snippet: "…",
          score: 2,
          paper_id: 9,
          question_id: "q-42",
          match_count: 3,
        },
        { type: "question", title: "函数", snippet: "…", score: 3, question_id: "q-1", match_count: 1 },
      ],
      count: 3,
    });
    renderSearch();

    fireEvent.change(screen.getByPlaceholderText("搜索对话、试卷、资料、题目…"), {
      target: { value: "数列" },
    });

    expect(await screen.findByText("数列讨论")).toBeInTheDocument();
    expect(screen.getByText("6 条匹配")).toBeInTheDocument();
    expect(screen.getByText("3 条匹配")).toBeInTheDocument();
    expect(screen.queryByText("1 条匹配")).not.toBeInTheDocument();
  });

  it("会话/试卷结果携带 message / question 锚点跳转", async () => {
    vi.useRealTimers();
    searchMock.mockResolvedValue({
      query: "数列",
      results: [
        {
          type: "conversation",
          title: "数列讨论",
          snippet: "…",
          score: 1,
          conversation_id: 5,
          message_id: 12,
          match_count: 6,
        },
        {
          type: "paper",
          title: "函数专题卷",
          snippet: "…",
          score: 2,
          paper_id: 9,
          question_id: "q-42",
          match_count: 3,
        },
        {
          type: "conversation",
          title: "无锚点会话",
          snippet: "…",
          score: 3,
          conversation_id: 8,
          match_count: 1,
        },
      ],
      count: 3,
    });
    renderSearch();

    // 点击结果会关闭搜索框，因此每个锚点跳转都需要重新打开搜索
    fireEvent.change(screen.getByPlaceholderText("搜索对话、试卷、资料、题目…"), {
      target: { value: "数列" },
    });
    expect(await screen.findByText("数列讨论")).toBeInTheDocument();
    fireEvent.click(screen.getByText("数列讨论"));
    expect(screen.getByTestId("location").textContent).toBe("/chat/5?message=12");

    act(() => useUiStore.setState({ searchOpen: true }));
    fireEvent.change(screen.getByPlaceholderText("搜索对话、试卷、资料、题目…"), {
      target: { value: "数列" },
    });
    expect(await screen.findByText("函数专题卷")).toBeInTheDocument();
    fireEvent.click(screen.getByText("函数专题卷"));
    expect(screen.getByTestId("location").textContent).toBe("/papers/9?question=q-42");

    act(() => useUiStore.setState({ searchOpen: true }));
    fireEvent.change(screen.getByPlaceholderText("搜索对话、试卷、资料、题目…"), {
      target: { value: "数列" },
    });
    expect(await screen.findByText("无锚点会话")).toBeInTheDocument();
    fireEvent.click(screen.getByText("无锚点会话"));
    expect(screen.getByTestId("location").textContent).toBe("/chat/8");
  });

  it("match_count 缺省时按旧契约渲染（不报错、无徽标）", async () => {
    vi.useRealTimers();
    const results: GlobalSearchResult[] = [
      { type: "study_archive", title: "资料归档", snippet: "…", score: 1, archive_id: 3 },
    ];
    searchMock.mockResolvedValue({ query: "资料", results, count: 1 });
    renderSearch();

    fireEvent.change(screen.getByPlaceholderText("搜索对话、试卷、资料、题目…"), {
      target: { value: "资料" },
    });
    expect(await screen.findByText("资料归档")).toBeInTheDocument();
    expect(screen.queryByText(/条匹配/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("资料归档"));
    expect(screen.getByTestId("location").textContent).toBe("/materials/3");
  });
});
