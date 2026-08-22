import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { libraryApi } from "@/features/question-library/api";
import { GaokaoImportSheet } from "../gaokao-import-sheet";

vi.mock("@/features/question-library/api", () => ({
  libraryApi: { importGaokao: vi.fn() },
}));

const validJson = JSON.stringify([
  {
    question_id: "gk-2024-3",
    subject: "高中数学",
    stem: "函数 \\(f(x)=A\\sin x\\)",
    source: { exam_year: 2024, region: "全国", paper_name: "新课标I卷", question_number: "3" },
  },
]);

function renderSheet(onImported = vi.fn(), onOpenChange = vi.fn()) {
  const queryClient = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <GaokaoImportSheet open onImported={onImported} onOpenChange={onOpenChange} />
    </QueryClientProvider>,
  );
  return { onImported, onOpenChange };
}

describe("GaokaoImportSheet", () => {
  it("预检通过后提交，并在成功时通知列表刷新", async () => {
    vi.mocked(libraryApi.importGaokao).mockResolvedValue({ success: true, upserted: 1, question_ids: ["gk-2024-3"] });
    const callbacks = renderSheet();

    fireEvent.change(screen.getByPlaceholderText('粘贴题目数组，或 { "items": [...] }'), { target: { value: validJson } });
    fireEvent.click(await screen.findByRole("button", { name: "确认导入 1 题" }));

    await waitFor(() => expect(libraryApi.importGaokao).toHaveBeenCalledOnce());
    expect(callbacks.onImported).toHaveBeenCalledOnce();
    expect(callbacks.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("服务端失败后保留用户输入并显示错误", async () => {
    vi.mocked(libraryApi.importGaokao).mockRejectedValue(new Error("422: invalid source"));
    renderSheet();

    const input = screen.getByPlaceholderText('粘贴题目数组，或 { "items": [...] }');
    fireEvent.change(input, { target: { value: validJson } });
    fireEvent.click(await screen.findByRole("button", { name: "确认导入 1 题" }));

    expect(await screen.findByText("导入失败，输入已保留")).toBeInTheDocument();
    expect(input).toHaveValue(validJson);
  });
});
