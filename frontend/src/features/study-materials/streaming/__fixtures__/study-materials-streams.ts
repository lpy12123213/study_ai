/**
 * 由当前后端契约整理的固定 wire fixture。
 * 仅使用 backend/agent、study_materials workflow 与 task runtime 的现行事件形状。
 */
export type StudyMaterialsWireEvent = Record<string, unknown>;

export const legacyStudyMaterialsStream: StudyMaterialsWireEvent[] = [
  {
    taskId: "materials-legacy-1",
    seq: 1,
    type: "task_started",
    data: {
      taskId: "materials-legacy-1",
      status: "running",
      query: "函数单调性",
      subject: "高中数学",
      options: { preset: "standard" },
    },
  },
  {
    taskId: "materials-legacy-1",
    seq: 2,
    type: "status",
    data: { content: "Plan 阶段：规划（第 1 轮）…" },
  },
  {
    taskId: "materials-legacy-1",
    seq: 3,
    type: "thinking",
    data: { content: "先拆分定义、判定方法与典型误区。", delta: true },
  },
  {
    taskId: "materials-legacy-1",
    seq: 4,
    type: "tool_call",
    data: {
      step_id: "split-1",
      name: "split_knowledge_points",
      title: "拆分并识别核心知识点",
      arguments: { topic: "函数单调性", max_points: 4 },
    },
  },
  {
    taskId: "materials-legacy-1",
    seq: 5,
    type: "tool_result",
    data: {
      step_id: "split-1",
      name: "split_knowledge_points",
      title: "拆分并识别核心知识点",
      success: true,
      elapsed_ms: 820,
      output: { knowledge_points: ["定义与判定", "复合函数单调性", "常见误区"] },
      error: null,
    },
  },
  {
    taskId: "materials-legacy-1",
    seq: 6,
    type: "tool_call",
    data: {
      step_id: "web-1",
      name: "web_search_knowledge",
      title: "联网搜索相关学习资料",
      arguments: { topic: "函数单调性", knowledge_points: ["定义与判定"] },
    },
  },
  {
    taskId: "materials-legacy-1",
    seq: 7,
    type: "tool_result",
    data: {
      step_id: "web-1",
      name: "web_search_knowledge",
      title: "联网搜索相关学习资料",
      success: true,
      elapsed_ms: 26400,
      output: {
        items: [
          {
            knowledge_point: "定义与判定",
            results: [
              {
                title: "函数的单调性",
                url: "https://example.edu/monotonicity",
                snippet: "介绍定义与判定方法。",
              },
            ],
          },
        ],
      },
    },
  },
  {
    taskId: "materials-legacy-1",
    seq: 8,
    type: "done",
    data: {
      success: true,
      material: {
        topic: "函数单调性 · 自学讲义",
        subject: "高中数学",
        markdown: "# 函数单调性\n\n理解单调性的关键在于定义域内任取两点。",
        passed: true,
        md_url: "/api/media/generated/functions.md",
      },
    },
  },
];

export const codexSnapshotStream: StudyMaterialsWireEvent[] = [
  {
    taskId: "materials-codex-1",
    seq: 1,
    type: "task_started",
    data: { taskId: "materials-codex-1", query: "牛顿第二定律", status: "running" },
  },
  {
    taskId: "materials-codex-1",
    seq: 2,
    type: "workflow_stage",
    data: { stage: "research", last_successful_stage: "plan" },
  },
  {
    taskId: "materials-codex-1",
    seq: 3,
    type: "reasoning_delta",
    data: { content: "先验证力、质量、加速度的条件。" },
  },
  {
    taskId: "materials-codex-1",
    seq: 4,
    type: "tool_call",
    data: {
      id: "codex-web-1",
      name: "web_search_knowledge",
      arguments: { query_hint: "牛顿第二定律 适用条件" },
      runtime: "codex_runtime",
    },
  },
  {
    taskId: "materials-codex-1",
    seq: 5,
    type: "tool_result",
    data: {
      id: "codex-web-1",
      content: JSON.stringify({
        success: true,
        results: [{ title: "Newton's second law", url: "https://example.org/newton" }],
      }),
      is_error: false,
      runtime: "codex_runtime",
    },
  },
  {
    taskId: "materials-codex-1",
    seq: 6,
    type: "text_delta",
    data: { content: "# 第一版\n\n草稿。" },
  },
  {
    taskId: "materials-codex-1",
    seq: 7,
    type: "text_delta",
    data: { content: "# 第二版\n\n修订后的完整草稿。" },
  },
  {
    taskId: "materials-codex-1",
    seq: 8,
    type: "done",
    data: {
      success: true,
      material: {
        topic: "牛顿第二定律",
        subject: "高中物理",
        markdown: "# 第二版\n\n修订后的完整草稿。",
        passed: true,
      },
    },
  },
];

export const failedRecoveryStream: StudyMaterialsWireEvent[] = [
  {
    taskId: "materials-failed-1",
    seq: 1,
    type: "task_started",
    data: { taskId: "materials-failed-1", query: "英语虚拟语气", status: "running" },
  },
  {
    taskId: "materials-failed-1",
    seq: 2,
    type: "tool_call",
    data: {
      step_id: "research-1",
      name: "web_search_knowledge",
      arguments: { topic: "英语虚拟语气" },
    },
  },
  {
    taskId: "materials-failed-1",
    seq: 3,
    type: "tool_result",
    data: {
      step_id: "research-1",
      name: "web_search_knowledge",
      success: false,
      output: {},
      error: "llm_request_failed",
    },
  },
  {
    taskId: "materials-failed-1",
    seq: 4,
    type: "recovery_available",
    data: {
      code: "quality_gate_not_met",
      stage: "research",
      recoverable: true,
      issues: ["来源覆盖不足"],
    },
  },
  {
    taskId: "materials-failed-1",
    seq: 5,
    type: "error",
    data: {
      message: "quality_gate_not_met",
      code: "quality_gate_not_met",
      stage: "research",
      recoverable: true,
    },
  },
];

export const continuationChildStart: StudyMaterialsWireEvent = {
  taskId: "materials-child-2",
  seq: 1,
  type: "task_started",
  data: {
    taskId: "materials-child-2",
    parentTaskId: "materials-parent-1",
    query: "函数单调性",
    status: "running",
  },
};

/**
 * 质量审查未通过 → 修订 + 检索补充 → 降级完成的 codex 流。
 * 覆盖 revision_required / research_retry_required / quality_degraded / degraded done。
 */
export const degradedRevisionStream: StudyMaterialsWireEvent[] = [
  {
    taskId: "materials-degraded-1",
    seq: 1,
    type: "task_started",
    data: { taskId: "materials-degraded-1", query: "函数单调性", status: "running" },
  },
  {
    taskId: "materials-degraded-1",
    seq: 2,
    type: "workflow_stage",
    data: { stage: "research", last_successful_stage: "plan", revision_attempts: 0 },
  },
  {
    taskId: "materials-degraded-1",
    seq: 3,
    type: "subagent_start",
    data: { knowledge_point: "定义与判定" },
  },
  {
    taskId: "materials-degraded-1",
    seq: 4,
    type: "subagent_end",
    data: { knowledge_point: "定义与判定" },
  },
  {
    taskId: "materials-degraded-1",
    seq: 5,
    type: "quality_report",
    data: {
      passed: false,
      failed_checks: ["research_evidence_missing:kp-1"],
      per_knowledge_point: {
        "kp-1": {
          passed: false,
          failed_checks: ["research_evidence_missing:kp-1"],
          source_count: 1,
          source_classes: ["web"],
        },
      },
    },
  },
  {
    taskId: "materials-degraded-1",
    seq: 6,
    type: "revision_required",
    data: { issues: ["「定义与判定」检索证据不足"], remaining_attempts: 2 },
  },
  {
    taskId: "materials-degraded-1",
    seq: 7,
    type: "research_retry_required",
    data: { point_ids: ["kp-1"], attempt: 1, remaining_attempts: 1 },
  },
  {
    taskId: "materials-degraded-1",
    seq: 8,
    type: "workflow_stage",
    data: { stage: "revise", last_successful_stage: "research", revision_attempts: 1 },
  },
  {
    taskId: "materials-degraded-1",
    seq: 9,
    type: "text_delta",
    data: { content: "# 函数单调性\n\n修订后的完整草稿。" },
  },
  {
    taskId: "materials-degraded-1",
    seq: 10,
    type: "quality_degraded",
    data: { issues: ["「定义与判定」来源类型单一"], revision_attempts: 2 },
  },
  {
    taskId: "materials-degraded-1",
    seq: 11,
    type: "done",
    data: {
      success: true,
      degraded: true,
      material: {
        topic: "函数单调性",
        subject: "高中数学",
        markdown: "# 函数单调性\n\n修订后的完整草稿。",
        passed: false,
        issues: ["「定义与判定」来源类型单一"],
        md_url: "/api/media/generated/degraded.md",
      },
      quality_report: {
        passed: false,
        failed_checks: ["source_classes_missing:kp-1"],
        per_knowledge_point: {
          "kp-1": {
            passed: false,
            failed_checks: ["source_classes_missing:kp-1"],
            source_count: 2,
            source_classes: ["web"],
          },
        },
      },
    },
  },
];

/** 检索服务故障：research_tool_outage 恢复码与质量门文案必须区分。 */
export const researchOutageStream: StudyMaterialsWireEvent[] = [
  {
    taskId: "materials-outage-1",
    seq: 1,
    type: "task_started",
    data: { taskId: "materials-outage-1", query: "光合作用", status: "running" },
  },
  {
    taskId: "materials-outage-1",
    seq: 2,
    type: "workflow_stage",
    data: { stage: "research", last_successful_stage: "plan" },
  },
  {
    taskId: "materials-outage-1",
    seq: 3,
    type: "recovery_available",
    data: {
      code: "research_tool_outage",
      stage: "research",
      recoverable: true,
      issues: ["检索服务暂时不可用"],
    },
  },
  {
    taskId: "materials-outage-1",
    seq: 4,
    type: "error",
    data: {
      message: "research_tool_outage",
      code: "research_tool_outage",
      stage: "research",
      recoverable: true,
    },
  },
];
