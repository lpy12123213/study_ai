import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeChatEvent } from "../../streaming/contract";
import { chatProjectionReducer, initialChatProjection, type ChatProjectionState } from "../../model/reducer";
import {
  computeAndPlotStream,
  createPaperStream,
  parallelToolsStream,
  type ChatWireEvent,
} from "../../streaming/__fixtures__/chat-streams";
import { ToolInspector } from "../tool-inspector";
import { ToolInspectorHost } from "../tool-inspector-host";

function project(events: ChatWireEvent[]): ChatProjectionState {
  let state = initialChatProjection();
  let at = 1_000;
  for (const raw of events) {
    const normalized = normalizeEvent(raw);
    if (!normalized) continue;
    const decoded = decodeChatEvent(normalized);
    if (!decoded) continue;
    state = chatProjectionReducer(state, { type: "event", event: decoded, at });
    at += 100;
  }
  return state;
}

function renderInspector(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>);
}

function stubMatchMedia(predicate: (query: string) => boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: predicate(query),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ToolInspector", () => {
  it("默认打开「结果」标签页并展示领域适配视图", () => {
    const { turn } = project(parallelToolsStream);
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_p1" onSelectTool={() => {}} />);
    expect(screen.getByText("共找到", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    // 头部：工具名 + 轮次
    expect(screen.getByText("题库搜索")).toBeInTheDocument();
    expect(screen.getByText("第 1 轮")).toBeInTheDocument();
  });

  it("「参数」标签页展示结构化参数并隐藏空字段", async () => {
    const user = userEvent.setup();
    const { turn } = project(parallelToolsStream);
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_p1" onSelectTool={() => {}} />);
    await user.click(screen.getByRole("tab", { name: "参数" }));
    expect(screen.getByText("keyword")).toBeInTheDocument();
    expect(screen.getByText("三角函数")).toBeInTheDocument();
    expect(screen.getByText("limit")).toBeInTheDocument();
  });

  it("「来源」标签页：题库结果为空时给出说明，Web 搜索展示链接", async () => {
    const user = userEvent.setup();
    const { turn } = project(parallelToolsStream);
    const { rerender } = render(
      <MemoryRouter>
        <ToolInspector turn={turn} selectedToolId="call_p1" onSelectTool={() => {}} />
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("tab", { name: "来源" }));
    expect(screen.getByText("该工具没有可验证的来源。")).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <ToolInspector turn={turn} selectedToolId="call_p2" onSelectTool={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: /诱导公式速记/ })).toHaveAttribute("href", "https://example.edu/trig");
    expect(screen.getByText("网络")).toBeInTheDocument();
  });

  it("「概览」标签页展示统计并可切换选中工具", async () => {
    const user = userEvent.setup();
    const { turn } = project(parallelToolsStream);
    const onSelect = vi.fn();
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_p1" onSelectTool={onSelect} />);
    await user.click(screen.getByRole("tab", { name: "概览" }));
    expect(screen.getByText("工具数")).toBeInTheDocument();
    expect(screen.getByText("成功")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /网络搜索/ }));
    expect(onSelect).toHaveBeenCalledWith("call_p2");
    // 切换后回到「结果」标签页
    expect(screen.getByRole("tab", { name: "结果" })).toHaveAttribute("data-state", "active");
  });

  it("「详情」标签页：原始 JSON 默认折叠，展开后可见；展示客户端观察时间", async () => {
    const user = userEvent.setup();
    const { turn } = project(parallelToolsStream);
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_p2" onSelectTool={() => {}} />);
    await user.click(screen.getByRole("tab", { name: "详情" }));
    expect(screen.getByText("开始接收（客户端观察）")).toBeInTheDocument();
    expect(screen.getByText("结果接收（客户端观察）")).toBeInTheDocument();
    // 默认折叠：JSON 内容不可见
    expect(screen.queryByText(/"query": "三角函数 诱导公式 总结"/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /原始参数（JSON）/ }));
    expect(screen.getByText(/"query": "三角函数 诱导公式 总结"/)).toBeInTheDocument();
  });

  it("绘图工具：结果页展示完整图像与文件信息", () => {
    const { turn } = project(computeAndPlotStream);
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_c2" onSelectTool={() => {}} />);
    const img = screen.getByRole("img", { name: "plot-abc123.png" });
    expect(img).toHaveAttribute("src", "/api/media/generated/plot-abc123.png");
    expect(screen.getByText("37.3 KB")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /打开原图/ })).toHaveAttribute("href", "/api/media/generated/plot-abc123.png");
  });

  it("科学计算：结果页展示表达式与结构化结果", () => {
    const { turn } = project(computeAndPlotStream);
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_c1" onSelectTool={() => {}} />);
    expect(screen.getByText(/result=sp.solve/)).toBeInTheDocument();
    expect(screen.getByText("[2, 3]")).toBeInTheDocument();
  });

  it("创建试卷：结果页提供试卷入口，来源页为内部链接", async () => {
    const user = userEvent.setup();
    const { turn } = project(createPaperStream);
    renderInspector(<ToolInspector turn={turn} selectedToolId="call_cp1" onSelectTool={() => {}} />);
    expect(screen.getByRole("link", { name: /打开试卷（ID: 208）/ })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "来源" }));
    expect(screen.getByText("试卷")).toBeInTheDocument();
  });
});

describe("ToolInspectorHost", () => {
  const { turn } = project(createPaperStream);

  it("宽屏附着面板：Escape 关闭并把焦点还给触发按钮", async () => {
    stubMatchMedia((q) => q.includes("min-width"));
    const user = userEvent.setup();

    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <MemoryRouter>
          <button type="button" onClick={() => setOpen(true)}>
            trigger
          </button>
          {open ? (
            <ToolInspectorHost turn={turn} selectedToolId="call_cp1" onSelectTool={() => {}} onClose={() => setOpen(false)} />
          ) : null}
        </MemoryRouter>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "trigger" });
    trigger.focus();
    await user.click(trigger);
    expect(screen.getByRole("complementary", { name: "工具检查器" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("complementary", { name: "工具检查器" })).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });

  it("移动端底部面板：拖拽手柄在 70/90dvh 间切换", () => {
    stubMatchMedia((q) => q.includes("max-width"));

    render(
      <MemoryRouter>
        <ToolInspectorHost turn={turn} selectedToolId="call_cp1" onSelectTool={() => {}} onClose={() => {}} />
      </MemoryRouter>,
    );
    const dialog = screen.getByRole("dialog", { name: "工具检查器" });
    expect(dialog.getAttribute("style")).toContain("70dvh");

    const handle = screen.getByRole("separator", { name: "拖拽调整面板高度" });
    fireEvent.pointerDown(handle, { clientY: 300 });
    fireEvent.pointerUp(handle, { clientY: 100 });
    expect(dialog.getAttribute("style")).toContain("90dvh");

    fireEvent.pointerDown(handle, { clientY: 100 });
    fireEvent.pointerUp(handle, { clientY: 300 });
    expect(dialog.getAttribute("style")).toContain("70dvh");
  });

  it("中屏渲染为覆盖式 Sheet", () => {
    stubMatchMedia(() => false);
    render(
      <MemoryRouter>
        <ToolInspectorHost turn={turn} selectedToolId="call_cp1" onSelectTool={() => {}} onClose={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("dialog", { name: "工具检查器" })).toBeInTheDocument();
  });
});
