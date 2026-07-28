import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { StudyMaterialResult } from "@/shared/api/types";
import { initialStudyMaterialsProjection } from "../../model/reducer";
import { MaterialResultCard } from "../material-result-card";
import { MaterialsWelcome } from "../materials-welcome";
import { RecoveryCard } from "../recovery-card";
import { StageProgress } from "../stage-progress";

describe("study-materials conversation UI", () => {
  it("空态显示意图优先标题、四种预设与最近成果", () => {
    render(
      <MemoryRouter>
        <MaterialsWelcome
          preset="standard"
          onPresetChange={vi.fn()}
          onExample={vi.fn()}
          archives={[
            {
              id: 31,
              subject: "高中物理",
              topic: "牛顿第二定律",
              preset: "standard",
              created_at: "2026-07-26T08:00:00",
            },
          ]}
          archivesPending={false}
          recentTasks={[]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText(/说出想学的主题/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /快速/ })).toBeInTheDocument();
    expect(screen.getByText("牛顿第二定律")).toBeInTheDocument();
  });

  it("阶段条明确标注推断语义", () => {
    const state = initialStudyMaterialsProjection();
    render(<StageProgress stages={state.stages} />);
    expect(screen.getByText(/阶段由当前工具活动推断/)).toBeInTheDocument();
  });

  it("完成卡支持展开正文与触发 LaTeX 转换", () => {
    const onConvert = vi.fn();
    const result: StudyMaterialResult = {
      material: {
        topic: "函数单调性",
        subject: "高中数学",
        markdown: "# 函数单调性\n\n正文",
        passed: true,
      },
    };
    render(
      <MaterialResultCard
        result={result}
        markdown={result.material?.markdown ?? ""}
        preset="standard"
        convertingLatex={false}
        onConvertLatex={onConvert}
      />,
    );
    expect(screen.getByText("讲义已完成")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "转 LaTeX" }));
    expect(onConvert).toHaveBeenCalledOnce();
  });

  it("失败卡把三个恢复动作映射到后端 continue mode", () => {
    const onContinue = vi.fn();
    render(
      <RecoveryCard
        message="检索服务请求超时"
        recovery={{ stage: "research", issues: [], recoverable: true }}
        onContinue={onContinue}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "从失败阶段继续" }));
    fireEvent.click(screen.getByRole("button", { name: "重试检索" }));
    fireEvent.click(screen.getByRole("button", { name: "重新规划" }));
    expect(onContinue.mock.calls.map(([mode]) => mode)).toEqual([
      "resume_failed_stage",
      "retry_search",
      "replan_from_failure",
    ]);
  });
});
