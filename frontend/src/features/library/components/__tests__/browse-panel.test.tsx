import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { libraryApi } from "@/features/question-library/api";
import { BrowsePanel } from "../browse-panel";

vi.mock("@/features/question-library/api", () => ({
  libraryApi: {
    items: vi.fn(),
    getItem: vi.fn(),
    hide: vi.fn(),
    unhide: vi.fn(),
    star: vi.fn(),
    unstar: vi.fn(),
    bulkDelete: vi.fn(),
    exportToBasket: vi.fn(),
    importGaokao: vi.fn(),
  },
}));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

function renderBrowse(initialPath = "/library?tab=browse") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <BrowsePanel onGoGenerate={vi.fn()} />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("BrowsePanel 高考真题区域", () => {
  const itemsMock = vi.mocked(libraryApi.items);
  const detailMock = vi.mocked(libraryApi.getItem);

  beforeEach(() => {
    vi.clearAllMocks();
    itemsMock.mockResolvedValue({ total: 0, items: [], limit: 20, offset: 0 });
    detailMock.mockResolvedValue({ library_item: {}, question_cache: {} });
  });

  it(
    "默认请求普通题库，切换后把 gaokao 区域写入 URL 和独立查询",
    async () => {
      renderBrowse();

      await waitFor(() => expect(itemsMock).toHaveBeenCalled());
      expect(itemsMock.mock.calls[0][0]).toMatchObject({ area: "general" });

      fireEvent.click(screen.getByRole("button", { name: "高考真题" }));

      await waitFor(() =>
        expect(itemsMock.mock.calls.some(([query]) => query?.area === "gaokao")).toBe(true),
      );
      expect(screen.getByTestId("location")).toHaveTextContent("area=gaokao");
    },
    10_000,
  );

  it("从 URL 恢复结构化真题筛选，并在卡片内按需加载 LaTeX 答案", async () => {
    itemsMock.mockResolvedValue({
      total: 1,
      limit: 20,
      offset: 0,
      items: [
        {
          question_id: "gk-2024-3",
          subject: "高中数学",
          stem: "<p>函数 \\(f(x)=A\\sin x\\) 的图象如下</p><img src=\"https://example.com/q.png\" alt=\"原题图\">",
          question_type: "单选题",
          has_answer: true,
          has_analysis: true,
          library_area: "gaokao",
          gaokao_source: {
            exam_year: 2024,
            region: "全国",
            paper_name: "2024年新课标I卷数学",
            paper_variant: "新课标I卷",
            question_number: "3",
            source_url: "https://example.com/paper.pdf",
            verified: false,
          },
        },
      ],
    });
    detailMock.mockResolvedValue({
      library_item: {},
      question_cache: {
        answer: "D",
        analysis: "在区间 \\([-\\frac{\\pi}{12},\\frac{\\pi}{4}]\\) 上递增。",
      },
    });

    renderBrowse(
      "/library?tab=browse&area=gaokao&subject=数学&year=2024&region=全国&paper=新课标I卷&number=3",
    );

    expect(await screen.findByText("2024 · 全国 · 新课标I卷 · 第 3 题")).toBeInTheDocument();
    expect(itemsMock.mock.calls.at(-1)?.[0]).toMatchObject({
      area: "gaokao",
      subject: "数学",
      year: "2024",
      region: "全国",
      paper_name: "新课标I卷",
      question_number: "3",
    });
    expect(screen.getByText("函数", { exact: false }).querySelector(".katex")).not.toBeNull();
    expect(screen.getByAltText("原题图")).toBeInTheDocument();

    fireEvent.click(screen.getByText("函数", { exact: false }));

    expect(await screen.findByText("D")).toBeInTheDocument();
    expect(detailMock).toHaveBeenCalledWith("gk-2024-3");
    expect(screen.getByText("在区间", { exact: false }).querySelector(".katex")).not.toBeNull();
    expect(screen.queryByRole("dialog", { name: "题目详情" })).not.toBeInTheDocument();
  });

  it("真题空状态引导结构化导入而不是 AI 出题", async () => {
    renderBrowse("/library?tab=browse&area=gaokao");

    expect(await screen.findByText("暂未找到高考真题")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "导入高考真题" })).toHaveLength(2);
    expect(screen.queryByRole("button", { name: /AI 出题/ })).not.toBeInTheDocument();
  });
});
