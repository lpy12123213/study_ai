import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { normalizeEvent } from "@/lib/sse";
import type { StudyMaterialResult } from "@/shared/api/types";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  initialStudyMaterialsProjection,
  studyMaterialsProjectionReducer,
} from "../../model/reducer";
import { selectKnowledgePointBoard, selectResultMarkdown } from "../../model/selectors";
import { decodeStudyMaterialsEvent } from "../../streaming/contract";
import {
  codexSnapshotStream,
  degradedRevisionStream,
  legacyStudyMaterialsStream,
  type StudyMaterialsWireEvent,
} from "../../streaming/__fixtures__/study-materials-streams";
import { KnowledgePointBoard } from "../knowledge-point-board";
import { MaterialResultCard } from "../material-result-card";
import { MaterialsWelcome } from "../materials-welcome";
import { RecoveryCard } from "../recovery-card";
import { ResumeBanner } from "../resume-banner";
import { RevisionStrip } from "../revision-strip";
import { StageProgress } from "../stage-progress";
import { StudyMaterialsUserRequest } from "../user-request";

function renderWithProviders(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function projectWire(events: StudyMaterialsWireEvent[]) {
  let state = initialStudyMaterialsProjection();
  let at = 1_000;
  for (const raw of events) {
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

  it("最近生成任务可点击跳转到 ?task= 恢复入口", () => {
    render(
      <MemoryRouter>
        <TooltipProvider>
          <MaterialsWelcome
            preset="standard"
            onPresetChange={vi.fn()}
            onExample={vi.fn()}
            archives={[]}
            archivesPending={false}
            recentTasks={[
              {
                id: "task-42",
                task_type: "study_materials",
                title: "函数单调性",
                status: "running",
                progress: 40,
              },
            ]}
          />
        </TooltipProvider>
      </MemoryRouter>,
    );
    const link = screen.getByRole("link", { name: /函数单调性/ });
    expect(link).toHaveAttribute("href", "/materials?task=task-42");
  });

  it("阶段条：推断声明只在阶段确实来自推断时出现，progress 渲染百分比", () => {
    // legacy 流没有权威 workflow_stage，必须保留推断声明。
    const legacy = projectWire(legacyStudyMaterialsStream.slice(0, 5));
    const { unmount } = render(<StageProgress stages={legacy.stages} progress={42} />);
    expect(screen.getByText(/阶段由当前工具活动推断/)).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
    unmount();

    // 初始（全 pending）没有推断依据，不显示声明。
    const initial = initialStudyMaterialsProjection();
    const { unmount: unmountInitial } = render(<StageProgress stages={initial.stages} />);
    expect(screen.queryByText(/阶段由当前工具活动推断/)).not.toBeInTheDocument();
    unmountInitial();

    // 权威 workflow_stage 覆盖当前阶段后摘掉声明。
    const authoritative = projectWire([
      { type: "task_started", seq: 1, taskId: "t-auth", data: { taskId: "t-auth" } },
      { type: "workflow_stage", seq: 2, data: { stage: "plan" } },
    ]);
    render(<StageProgress stages={authoritative.stages} />);
    expect(screen.queryByText(/阶段由当前工具活动推断/)).not.toBeInTheDocument();
  });

  it("知识点看板：检索中展示实时行", () => {
    const running = projectWire(degradedRevisionStream.slice(0, 3));
    renderWithProviders(<KnowledgePointBoard board={selectKnowledgePointBoard(running)} />);
    expect(screen.getByText("定义与判定")).toBeInTheDocument();
    expect(screen.getByText("检索中")).toBeInTheDocument();
  });

  it("知识点看板：审查未通过展示来源统计与中文失败检查", () => {
    const reviewed = projectWire(degradedRevisionStream.slice(0, 6));
    renderWithProviders(<KnowledgePointBoard board={selectKnowledgePointBoard(reviewed)} />);
    expect(screen.getByText("定义与判定")).toBeInTheDocument();
    expect(screen.getByText("1 个来源")).toBeInTheDocument();
    expect(screen.getByText("网页检索")).toBeInTheDocument();
    expect(screen.getAllByText("检索证据不足（kp-1）").length).toBeGreaterThan(0);
    expect(screen.getByText(/未通过检查/)).toBeInTheDocument();
  });

  it("修订条：审查未通过带剩余次数，检索补充带进度", () => {
    const { unmount } = render(
      <RevisionStrip issues={["「定义与判定」检索证据不足"]} remainingAttempts={2} />,
    );
    expect(screen.getByText(/质量审查未通过/)).toBeInTheDocument();
    expect(screen.getByText(/剩余 2 次修订机会/)).toBeInTheDocument();
    expect(screen.getByText("「定义与判定」检索证据不足")).toBeInTheDocument();
    unmount();

    render(
      <RevisionStrip
        issues={[]}
        researchRetry={{ pointIds: ["kp-1", "kp-2"], attempt: 1, remainingAttempts: 1 }}
      />,
    );
    expect(screen.getByText(/检索补充中 · 第 1 次，共 2 个知识点/)).toBeInTheDocument();
  });

  it("降级完成：结果卡显示质量警示但仍可下载", () => {
    const state = projectWire(degradedRevisionStream);
    const result = state.result;
    if (!result) throw new Error("fixture should finish with a result");
    renderWithProviders(
      <MaterialResultCard result={result} markdown={selectResultMarkdown(state)} preset="standard" />,
    );
    expect(screen.getByText("本次成果未完全通过质量审查")).toBeInTheDocument();
    expect(screen.getByText("「定义与判定」来源类型单一")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /下载 Markdown/ })).toBeInTheDocument();
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
    renderWithProviders(
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

  it("复制 Markdown 按钮写入剪贴板", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const result: StudyMaterialResult = {
      material: { topic: "函数单调性", markdown: "# 正文", passed: true },
    };
    renderWithProviders(
      <MaterialResultCard result={result} markdown="# 正文" preset="standard" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /复制 Markdown/ }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("# 正文"));
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

  it("不可恢复失败提供同参「重新生成」", () => {
    const onRegenerate = vi.fn();
    render(
      <RecoveryCard
        message="上游模型不可用"
        recovery={{ stage: "write", issues: [], recoverable: false }}
        onContinue={vi.fn()}
        onRegenerate={onRegenerate}
      />,
    );
    expect(screen.queryByRole("button", { name: "从失败阶段继续" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重新生成" }));
    expect(onRegenerate).toHaveBeenCalledOnce();
  });

  it("research_tool_outage 使用专属文案，与质量门失败区分", () => {
    render(
      <RecoveryCard
        message="research_tool_outage"
        recovery={{ stage: "research", code: "research_tool_outage", issues: [], recoverable: true }}
        onContinue={vi.fn()}
      />,
    );
    expect(screen.getByText(/检索服务暂时不可用，稍后可直接继续/)).toBeInTheDocument();
  });

  it("已完成任务的续播横幅切换为恢复视图语义", () => {
    const { unmount } = render(
      <ResumeBanner title="函数单调性" status="completed" onResume={vi.fn()} onDiscard={vi.fn()} />,
    );
    expect(screen.getByText("检测到已完成的生成任务")).toBeInTheDocument();
    expect(screen.getByText(/可重新接收输出并恢复视图/)).toBeInTheDocument();
    unmount();
    render(<ResumeBanner title="函数单调性" status="running" onResume={vi.fn()} onDiscard={vi.fn()} />);
    expect(screen.getByText("生成仍在进行中")).toBeInTheDocument();
    expect(screen.getByText("继续接收生成")).toBeInTheDocument();
  });

  it("请求回声展示全部参数并支持编辑重跑", () => {
    const onEdit = vi.fn();
    render(
      <StudyMaterialsUserRequest
        query="函数单调性"
        subject="高中数学"
        preset="standard"
        requirements="偏高考难度"
        withQuestions
        withDiagrams={false}
        extraTools={false}
        preferLocalArchive
        maxPoints={6}
        onEditRerun={onEdit}
      />,
    );
    expect(screen.getByText("含练习题")).toBeInTheDocument();
    expect(screen.getByText("优先本地档案")).toBeInTheDocument();
    expect(screen.getByText("最多 6 个知识点")).toBeInTheDocument();
    expect(screen.getByText("要求：偏高考难度")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /编辑并重跑/ }));
    expect(onEdit).toHaveBeenCalledOnce();
  });

  it("codex 快照流：done 前看板与阶段均可由事件驱动", () => {
    const state = projectWire(codexSnapshotStream.slice(0, -1));
    expect(state.markdownSnapshot).toContain("第二版");
    expect(state.snapshotVersion).toBe(2);
  });
});
