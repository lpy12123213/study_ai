import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
import {
  initialStudyMaterialsProjection,
  studyMaterialsProjectionReducer,
} from "../../model/reducer";
import { traceAgentStream } from "../../streaming/__fixtures__/study-materials-streams";
import { ProcessPanel, StudyTodoProgress } from "../process-panel";

function projectTrace() {
  let state = initialStudyMaterialsProjection();
  let at = 1_000;
  for (const raw of traceAgentStream) {
    const normalized = normalizeEvent(raw);
    if (!normalized) continue;
    const decoded = decodeStudyMaterialsEvent(normalized);
    if (!decoded) continue;
    state = studyMaterialsProjectionReducer(state, {
      type: "event",
      event: decoded,
      seq: normalized.seq,
      at,
    });
    at += 100;
  }
  return state;
}

function renderPanel() {
  const projection = projectTrace();
  return render(
    <ProcessPanel
      todos={Object.values(projection.todos)}
      traceByAgent={projection.traceByAgent}
      sectionStatus={projection.sectionStatus}
    />,
  );
}

describe("ProcessPanel", () => {
  it("渲染 TODO 清单（类型图标 + ref + 状态）", () => {
    renderPanel();
    expect(screen.getByLabelText("生成 TODO 清单")).toBeTruthy();
    expect(screen.getByText("光反应")).toBeTruthy();
    expect(screen.getByText("sec-1")).toBeTruthy();
    expect(screen.getByText("TODO 1/2")).toBeTruthy();
  });

  it("思考块默认折叠，点击展开合并后的思考文本", () => {
    renderPanel();
    expect(screen.queryByText(/先列大纲/)).toBeNull();
    // main 与 fill 泳道各有一个思考块；第一个是 main 泳道的合并块。
    fireEvent.click(screen.getAllByText(/思考过程 · /)[0]);
    expect(screen.getByText(/先列大纲。继续填充下一节。/)).toBeTruthy();
  });

  it("子泳道可展开折叠，fill 泳道挂章节状态徽标", () => {
    renderPanel();
    expect(screen.getByText("填充 · sec-1")).toBeTruthy();
    expect(screen.getByText("配图 · 1")).toBeTruthy();
    // section_fill ok → 泳道徽标「已完成」
    expect(screen.getAllByText("已完成").length).toBeGreaterThan(0);
    // 默认展开：笔记/工具/配图卡片可见
    expect(screen.getByText(/sec-1-photosynthesis/)).toBeTruthy();
    expect(screen.getByText("write_section")).toBeTruthy();
    expect(screen.getByText("配图 1")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("收起 填充 · sec-1 泳道"));
    expect(screen.queryByText(/sec-1-photosynthesis/)).toBeNull();
    expect(screen.getByLabelText("展开 填充 · sec-1 泳道")).toBeTruthy();
  });

  it("空数据不渲染 TODO 进度条；有数据时显示真实进度", () => {
    const { rerender } = render(<StudyTodoProgress todos={[]} />);
    expect(screen.queryByLabelText("真实 TODO 进度")).toBeNull();
    const projection = projectTrace();
    rerender(<StudyTodoProgress todos={Object.values(projection.todos)} />);
    expect(screen.getByLabelText("真实 TODO 进度")).toBeTruthy();
    expect(screen.getByText("TODO 1/2")).toBeTruthy();
  });
});
