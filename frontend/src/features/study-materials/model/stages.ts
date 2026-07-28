/**
 * 学习资料生成的阶段模型。
 *
 * legacy AgentCore 路径没有 workflow_stage 事件，阶段由当前工具活动推断
 * （与 backend/generation/study_materials/resume.py 的工具→阶段映射保持一致）。
 * UI 上必须保留「推断」标注，不伪装成后端权威状态。
 */
export type StudyStageKey = "plan" | "research" | "aggregate" | "write" | "review" | "export";

export const STUDY_STAGE_ORDER: StudyStageKey[] = ["plan", "research", "aggregate", "write", "review", "export"];

export const STUDY_STAGE_LABELS: Record<StudyStageKey, string> = {
  plan: "规划",
  research: "检索与研究",
  aggregate: "聚合大纲",
  write: "写作",
  review: "审查",
  export: "导出",
};

const TOOL_STAGE: Record<string, StudyStageKey> = {
  get_user_profile: "plan",
  split_knowledge_points: "plan",
  review_knowledge_points: "plan",
  web_search_knowledge: "research",
  browse_web_pages: "research",
  wikipedia_search: "research",
  mediawiki_search: "research",
  github_search: "research",
  stackexchange_search: "research",
  search_questions_by_knowledge: "research",
  research_knowledge_point: "research",
  detect_knowledge_type: "aggregate",
  aggregate_knowledge: "aggregate",
  synthesize_sources: "aggregate",
  generate_outline: "aggregate",
  generate_study_material: "write",
  generate_diagrams: "write",
  save_markdown_file: "write",
  critique_draft: "review",
  refine_draft: "review",
  review_content: "review",
  revise_markdown: "review",
  assemble_study_archive: "write",
  export_study_markdown: "export",
  convert_markdown_to_latex: "export",
  refine_latex: "export",
  compile_latex_to_pdf: "export",
};

/** 工具名 → UI 阶段；未识别返回 ""。 */
export function inferStageFromTool(name: string): StudyStageKey | "" {
  return TOOL_STAGE[name.trim()] ?? "";
}

/** codex workflow_stage 事件 → UI 阶段（仅在 codex 路径下使用）。 */
export function studyStageFromWorkflow(workflowStage: string): StudyStageKey | "" {
  switch (workflowStage.trim()) {
    case "plan":
      return "plan";
    case "research":
      return "research";
    case "draft":
      return "write";
    case "review":
    case "revise":
      return "review";
    case "accept":
      return "export";
    default:
      return "";
  }
}

/** 失败阶段标签兼容：workflow 六阶段与 legacy 四标签（taskStatus.last_failed_stage）。 */
export function studyStageFromFailure(stage: string): StudyStageKey | "" {
  const mapped = studyStageFromWorkflow(stage);
  if (mapped) return mapped;
  switch (stage.trim()) {
    case "search":
      return "research";
    case "aggregate":
      return "aggregate";
    case "write":
      return "write";
    case "export":
      return "export";
    default:
      return "";
  }
}
