/**
 * 学习资料工具的领域适配：中文显示名、一行输入意图、一行结果摘要、检索来源提取。
 * 全部防御性解析 unknown，未知工具回退原名 + 「执行完成」。
 */

/** 工具中文显示名（与后端工具注册名对齐）。 */
const TOOL_DISPLAY: Record<string, string> = {
  thinking: "推理并分析问题",
  get_user_profile: "读取用户画像并获取偏好",
  split_knowledge_points: "拆分并识别核心知识点",
  review_knowledge_points: "审核知识点覆盖及合理性",
  web_search_knowledge: "联网搜索相关学习资料",
  browse_web_pages: "浏览网页并提取正文内容",
  wikipedia_search: "检索维基百科相关条目",
  mediawiki_search: "检索开放知识库及百科内容",
  stackexchange_search: "检索问答社区相关讨论",
  github_search: "检索公开代码及技术资料",
  search_questions_by_knowledge: "从题库检索关联题目",
  aggregate_knowledge: "聚合多源资料并按知识点整理",
  synthesize_sources: "综合多源信息生成简报",
  detect_knowledge_type: "检测知识类型及结构特征",
  generate_outline: "生成自适应写作大纲",
  generate_study_material: "生成概念讲解及学习内容",
  critique_draft: "多维度审查并自我批判",
  refine_draft: "根据批判意见精炼修订",
  generate_diagrams: "生成教学示意图及配图",
  assemble_study_archive: "组装结构化学习档案",
  revise_markdown: "根据审查结果修订文档",
  save_markdown_file: "保存文档到本地文件",
  export_study_markdown: "导出文档并生成下载链接",
  convert_markdown_to_latex: "转换 LaTeX 排版源文件",
  compile_latex_to_pdf: "编译生成最终 PDF",
  research_knowledge_point: "深入研究知识点细节",
  review_content: "审查内容质量",
};

export function studyToolDisplayName(name: string): string {
  return TOOL_DISPLAY[name] ?? name;
}

/** quality_gate failed_checks 前缀 → 中文标签（带 :kp-N 后缀的检查会保留后缀）。 */
const FAILED_CHECK_LABELS: Record<string, string> = {
  plan_missing: "知识点规划缺失",
  research_evidence_missing: "检索证据不足",
  source_classes_missing: "来源类型单一",
  draft_coverage_missing: "草稿未覆盖知识点",
  markdown_missing: "正文缺失",
  markdown_lint_failed: "正文格式检查未通过",
  independent_review_failed: "独立审查未通过",
  review_draft_mismatch: "审查与草稿不一致",
};

export function studyFailedCheckLabel(check: string): string {
  const [head, ...rest] = check.split(":");
  const base = FAILED_CHECK_LABELS[head] ?? check;
  const suffix = rest.join(":").trim();
  return suffix ? `${base}（${suffix}）` : base;
}

/** quality_gate evidence.source_class → 中文标签。 */
const SOURCE_CLASS_LABELS: Record<string, string> = {
  web: "网页检索",
  wikipedia: "维基百科",
  mediawiki: "开放百科",
  page: "网页正文",
  stackexchange_search: "问答社区",
  github_search: "代码仓库",
};

export function studySourceClassLabel(sourceClass: string): string {
  return SOURCE_CLASS_LABELS[sourceClass] ?? sourceClass;
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function clip(text: string, max = 60): string {
  return text.length > max ? `${text.slice(0, max)}…` : text;
}

/** 一行输入意图摘要（由参数推导）。 */
export function studyToolIntent(name: string, args: unknown): string | undefined {
  const a = asRecord(args);
  if (!a) return undefined;
  const kp = asString(a.knowledge_point);
  const topic = asString(a.topic) ?? asString(a.query);
  switch (name) {
    case "split_knowledge_points": {
      const parts = [topic ? `主题：${topic}` : "", a.subject ? `学科：${asString(a.subject)}` : ""].filter(Boolean);
      return parts.length ? clip(parts.join(" · ")) : undefined;
    }
    case "web_search_knowledge": {
      const queries = Array.isArray(a.queries) ? a.queries.filter((q): q is string => typeof q === "string") : [];
      const q = queries[0] ?? asString(a.query);
      return q ? clip(`「${q}」${queries.length > 1 ? ` 等 ${queries.length} 组查询` : ""}`) : undefined;
    }
    case "search_questions_by_knowledge": {
      const kps = Array.isArray(a.knowledge_points) ? a.knowledge_points.filter((v): v is string => typeof v === "string") : [];
      const label = kp ?? (kps.length ? kps.join("、") : undefined);
      return label ? clip(`按知识点匹配题目：${label}`) : "按知识点匹配题库题目";
    }
    case "research_knowledge_point":
      return kp ? clip(kp) : undefined;
    case "browse_web_pages":
      return asString(a.url) ? clip(asString(a.url)!) : undefined;
    case "generate_study_material":
      return kp ?? (topic ? clip(topic) : undefined);
    case "critique_draft":
    case "refine_draft":
    case "revise_markdown":
    case "review_content":
      return "基于当前草稿";
    case "export_study_markdown":
    case "convert_markdown_to_latex":
    case "compile_latex_to_pdf":
      return topic ? clip(topic) : undefined;
    default:
      return kp ?? topic ? clip((kp ?? topic)!) : undefined;
  }
}

function countOf(value: unknown): number | undefined {
  return Array.isArray(value) ? value.length : undefined;
}

/** 一行结果摘要。 */
export function summarizeStudyToolResult(name: string, result: unknown): string {
  const r = asRecord(result) ?? {};
  switch (name) {
    case "split_knowledge_points": {
      const n = countOf(r.knowledge_points);
      return n ? `拆出 ${n} 个知识点` : "知识点拆分完成";
    }
    case "web_search_knowledge":
    case "wikipedia_search":
    case "mediawiki_search":
    case "stackexchange_search":
    case "github_search":
    case "browse_web_pages": {
      const n = countOf(r.results) ?? countOf(r.items) ?? countOf(r.sources) ?? countOf(r.pages);
      return n ? `获取 ${n} 个来源` : "检索完成";
    }
    case "search_questions_by_knowledge": {
      const n = countOf(r.questions) ?? countOf(r.items) ?? countOf(r.results);
      return n ? `匹配 ${n} 道题` : "题目检索完成";
    }
    case "aggregate_knowledge":
    case "synthesize_sources": {
      const n = countOf(r.knowledge_points) ?? countOf(r.sections);
      return n ? `整理 ${n} 个知识点的资料` : "资料聚合完成";
    }
    case "generate_outline":
      return "大纲已生成";
    case "generate_study_material": {
      const md = asString(r.markdown);
      return md ? `成稿约 ${md.length} 字` : "内容已生成";
    }
    case "critique_draft":
    case "review_content": {
      const issues = countOf(r.issues);
      return issues ? `发现 ${issues} 处待改进` : "审查完成";
    }
    case "refine_draft":
    case "revise_markdown":
      return "修订完成";
    case "generate_diagrams": {
      const n = countOf(r.diagrams) ?? countOf(r.images) ?? countOf(r.files);
      return n ? `生成 ${n} 幅示意图` : "示意图生成完成";
    }
    case "assemble_study_archive":
      return "档案组装完成";
    case "export_study_markdown":
      return asString(r.md_url) ?? asString(r.url) ? "已生成下载链接" : "导出完成";
    case "convert_markdown_to_latex":
      return asString(r.tex_url) ? "已生成 LaTeX 源文件" : "转换完成";
    case "compile_latex_to_pdf":
      return asString(r.pdf_url) ? "已生成 PDF" : "编译完成";
    case "research_knowledge_point":
      return "研究完成";
    default:
      return "执行完成";
  }
}

export interface StudySourceItem {
  title: string;
  url: string;
  snippet?: string;
  kind: string;
}

const SEARCH_TOOLS = new Set([
  "web_search_knowledge",
  "wikipedia_search",
  "mediawiki_search",
  "stackexchange_search",
  "github_search",
  "browse_web_pages",
]);

/** 从检索类工具结果中提取可点击来源（title/url/snippet）。 */
export function extractStudySources(name: string, result: unknown): StudySourceItem[] {
  const r = asRecord(result);
  if (!r) return [];
  const pools: unknown[] = [];
  if (SEARCH_TOOLS.has(name)) {
    pools.push(r.results, r.items, r.sources, r.pages);
  }
  if (name === "research_knowledge_point" || name === "aggregate_knowledge") {
    pools.push(r.sources, r.results);
  }
  for (const pool of pools) {
    if (!Array.isArray(pool)) continue;
    const items: StudySourceItem[] = [];
    for (const entry of pool) {
      const rec = asRecord(entry);
      if (!rec) continue;
      const url = asString(rec.url) ?? asString(rec.link);
      const title = asString(rec.title) ?? asString(rec.name) ?? url;
      if (!url || !title) continue;
      items.push({
        title: clip(title, 80),
        url,
        ...(asString(rec.snippet) ?? asString(rec.summary) ?? asString(rec.content)
          ? { snippet: clip(asString(rec.snippet) ?? asString(rec.summary) ?? asString(rec.content)!, 140) }
          : {}),
        kind: asString(rec.source) ?? asString(rec.provider) ?? name,
      });
    }
    if (items.length) return items.slice(0, 30);
  }
  return [];
}
