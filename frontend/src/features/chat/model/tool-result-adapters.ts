/**
 * 工具结果领域适配器：把解码后的工具参数/结果转为用户可读的一行摘要。
 * 每个适配器接收 unknown 并做防御性解析，不假设后端结构一定完整。
 */

const TOOL_DISPLAY_NAMES: Record<string, string> = {
  search_questions: "题库搜索",
  get_available_filters: "查询可用筛选",
  compose_paper_blueprint: "组卷方案配题",
  batch_get_question_details: "获取题目详情",
  select_best_question: "智能选题",
  create_paper: "创建试卷",
  get_papers: "查询试卷列表",
  get_question_detail: "查看题目详情",
  plot_function: "函数绘图",
  web_search: "网络搜索",
  python_scientific_compute: "科学计算",
  get_user_profile: "读取学习偏好",
  split_knowledge_points: "拆分核心知识点",
  review_knowledge_points: "校验知识点范围",
  web_search_knowledge: "联网检索相关学习资料",
  browse_web_pages: "阅读网页原文",
  wikipedia_search: "检索百科资料",
  mediawiki_search: "检索开放知识库",
  github_search: "检索公开学习仓库",
  stackexchange_search: "检索问答资料",
  search_questions_by_knowledge: "从题库检索关联题目",
  aggregate_knowledge: "聚合知识点资料",
  synthesize_sources: "综合多来源证据",
  detect_knowledge_type: "识别知识点类型",
  generate_outline: "生成讲义大纲",
  generate_study_material: "撰写知识点讲解",
  critique_draft: "审阅讲义草稿",
  refine_draft: "修订讲义草稿",
  generate_diagrams: "生成教学示意图",
  assemble_study_archive: "组装学习讲义",
  review_content: "质量审查",
  revise_markdown: "按审查意见修订",
  export_study_markdown: "导出 Markdown",
  save_markdown_file: "保存 Markdown",
  convert_markdown_to_latex: "转换 LaTeX",
  refine_latex: "修订 LaTeX",
  compile_latex_to_pdf: "编译 PDF",
};

export function toolDisplayName(name: string): string {
  return TOOL_DISPLAY_NAMES[name] ?? name ?? "工具调用";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function truncate(text: string, max = 48): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

/** 从工具参数推导一行意图摘要。 */
export function toolIntent(name: string, args: unknown): string | undefined {
  const a = asRecord(args);
  if (!a) return undefined;
  switch (name) {
    case "search_questions": {
      const keyword = typeof a.keyword === "string" ? a.keyword : "";
      return keyword ? `关键词「${truncate(keyword, 24)}」` : undefined;
    }
    case "web_search": {
      const query = typeof a.query === "string" ? a.query : "";
      return query ? `搜索「${truncate(query, 24)}」` : undefined;
    }
    case "web_search_knowledge":
    case "browse_web_pages":
    case "wikipedia_search":
    case "mediawiki_search":
    case "github_search":
    case "stackexchange_search": {
      const query =
        (typeof a.query_hint === "string" && a.query_hint) ||
        (typeof a.query === "string" && a.query) ||
        (typeof a.topic === "string" && a.topic) ||
        "";
      const points = Array.isArray(a.knowledge_points)
        ? a.knowledge_points.filter((item): item is string => typeof item === "string")
        : [];
      const target = query || points[0] || "";
      return target ? `研究「${truncate(target, 24)}」` : undefined;
    }
    case "search_questions_by_knowledge": {
      const points = Array.isArray(a.knowledge_points)
        ? a.knowledge_points.filter((item): item is string => typeof item === "string")
        : [];
      const target =
        points[0] ||
        (typeof a.knowledge_point === "string" ? a.knowledge_point : "") ||
        (typeof a.topic === "string" ? a.topic : "");
      return target ? `匹配「${truncate(target, 24)}」` : undefined;
    }
    case "aggregate_knowledge":
    case "synthesize_sources":
    case "detect_knowledge_type":
    case "generate_outline":
    case "generate_study_material":
    case "critique_draft":
    case "refine_draft":
    case "generate_diagrams":
    case "assemble_study_archive":
    case "review_content":
    case "revise_markdown": {
      const target =
        (typeof a.knowledge_point === "string" && a.knowledge_point) ||
        (Array.isArray(a.knowledge_points) && typeof a.knowledge_points[0] === "string"
          ? a.knowledge_points[0]
          : "") ||
        (typeof a.topic === "string" && a.topic) ||
        "";
      return target ? truncate(target, 32) : undefined;
    }
    case "plot_function": {
      const expr = typeof a.expr === "string" ? a.expr : "";
      return expr ? `绘制 ${truncate(expr, 32)}` : undefined;
    }
    case "python_scientific_compute": {
      const purpose = typeof a.purpose === "string" ? a.purpose.trim() : "";
      return purpose ? truncate(purpose, 32) : "运行计算代码";
    }
    case "create_paper": {
      const paperName = typeof a.paper_name === "string" ? a.paper_name : "";
      return paperName ? `创建「${truncate(paperName, 24)}」` : undefined;
    }
    case "get_question_detail": {
      const id = typeof a.question_id === "string" ? a.question_id : "";
      return id ? `题目 ${id}` : undefined;
    }
    case "batch_get_question_details": {
      const ids = Array.isArray(a.question_ids) ? a.question_ids.length : 0;
      return ids > 0 ? `${ids} 道题目` : undefined;
    }
    case "get_papers":
      return "查询已有试卷";
    case "get_available_filters":
      return "查询当前学科可用筛选";
    default:
      return undefined;
  }
}

/** 判断工具结果是否表达失败。 */
export function toolResultFailed(result: unknown): boolean {
  const r = asRecord(result);
  if (!r) return false;
  if (r.success === false) return true;
  return typeof r.error === "string" && r.error.length > 0;
}

function failureText(r: Record<string, unknown>): string {
  if (r.login_required === true || r.cookie_expired === true) return "题库登录态失效";
  const err = typeof r.error === "string" ? r.error : "";
  return err ? truncate(err, 48) : "执行失败";
}

/** 一行结果摘要；失败时返回失败原因。 */
export function summarizeToolResult(name: string, result: unknown): string {
  const r = asRecord(result);
  if (!r) return "已返回结果";
  if (toolResultFailed(r)) return failureText(r);

  switch (name) {
    case "search_questions": {
      const count = typeof r.count === "number" ? r.count : Array.isArray(r.questions) ? r.questions.length : 0;
      return `找到 ${count} 道候选题`;
    }
    case "web_search": {
      const n = Array.isArray(r.results) ? r.results.length : 0;
      return n > 0 ? `返回 ${n} 个来源` : "未检索到来源";
    }
    case "web_search_knowledge":
    case "browse_web_pages":
    case "wikipedia_search":
    case "mediawiki_search":
    case "github_search":
    case "stackexchange_search": {
      const direct = Array.isArray(r.results) ? r.results.length : 0;
      const grouped = Array.isArray(r.items)
        ? r.items.reduce((count, item) => {
            const record = asRecord(item);
            return count + (Array.isArray(record?.results) ? record.results.length : 0);
          }, 0)
        : 0;
      const count = direct || grouped;
      return count > 0 ? `聚合 ${count} 个来源` : "检索已完成";
    }
    case "search_questions_by_knowledge": {
      const direct = Array.isArray(r.questions) ? r.questions.length : 0;
      return direct > 0 ? `匹配 ${direct} 道关联题` : "题库匹配已完成";
    }
    case "aggregate_knowledge":
      return "资料已聚合";
    case "synthesize_sources":
      return "来源证据已综合";
    case "detect_knowledge_type":
      return "知识类型已识别";
    case "generate_outline":
      return "讲义大纲已生成";
    case "generate_study_material":
      return "知识点讲解已完成";
    case "critique_draft":
      return "草稿审阅已完成";
    case "refine_draft":
    case "revise_markdown":
      return "讲义修订已完成";
    case "generate_diagrams":
      return "教学示意图已生成";
    case "assemble_study_archive":
      return "讲义已组装";
    case "review_content":
      return r.passed === false ? "审查发现待改进项" : "质量审查已完成";
    case "export_study_markdown":
    case "save_markdown_file":
      return "Markdown 已导出";
    case "convert_markdown_to_latex":
    case "refine_latex":
      return "LaTeX 已生成";
    case "compile_latex_to_pdf":
      return "PDF 已编译";
    case "python_scientific_compute": {
      const repr = typeof r.result_repr === "string" ? r.result_repr : "";
      return repr ? `结果：${truncate(repr, 40)}` : "计算完成";
    }
    case "plot_function": {
      return r.cached === true ? "已生成图像（缓存）" : "已生成图像";
    }
    case "create_paper": {
      const id = typeof r.paper_id === "number" ? r.paper_id : undefined;
      return id !== undefined ? `试卷已创建（ID: ${id}）` : "试卷已创建";
    }
    case "get_papers": {
      const n = typeof r.count === "number" ? r.count : Array.isArray(r.papers) ? r.papers.length : 0;
      return `共 ${n} 份试卷`;
    }
    case "get_question_detail":
      return "已获取题目详情";
    case "batch_get_question_details": {
      const n = Array.isArray(r.questions) ? r.questions.length : 0;
      return n > 0 ? `已获取 ${n} 道题目详情` : "已获取题目详情";
    }
    case "get_available_filters":
      return "已获取可用筛选";
    case "compose_paper_blueprint":
      return "已完成配题";
    case "select_best_question":
      return "已完成选题";
    default:
      return "执行完成";
  }
}
