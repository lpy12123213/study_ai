/**
 * 检查器详情适配器：把工具参数/结果解码为领域详情视图与来源列表。
 * 每个适配器接收 unknown 并防御性解析，不直接信任后端结构（视觉规划 §7.8）。
 */

export interface QuestionItemView {
  id: string;
  stem?: string;
  difficulty?: string;
  knowledge: string[];
}

export interface WebResultItemView {
  title: string;
  url?: string;
  snippet?: string;
  publishedDate?: string;
}

export interface KeyValue {
  key: string;
  value: string;
}

export type ToolDetailView =
  | { kind: "questions"; count: number; keyword?: string; items: QuestionItemView[]; appliedFilters: KeyValue[] }
  | {
      kind: "compute";
      resultRepr?: string;
      resultType?: string;
      stdout?: string;
      warnings: string[];
      purpose?: string;
      code?: string;
    }
  | { kind: "plot"; url?: string; filename?: string; cached: boolean; bytes?: number }
  | { kind: "web"; query?: string; provider?: string; answer?: string; results: WebResultItemView[] }
  | { kind: "paper"; paperId?: number; message?: string }
  | { kind: "papers"; count: number; papers: KeyValue[] }
  | { kind: "generic" };

export interface SourceItemView {
  title: string;
  url?: string;
  snippet?: string;
  /** 来源类型：Web 链接 / 题库 / 内部试卷 / 生成文件。 */
  kind: "web" | "question-bank" | "paper" | "file";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string" && Boolean(v.trim())) : [];
}

function truncate(text: string, max = 4000): string {
  return text.length > max ? `${text.slice(0, max)}…（已截断）` : text;
}

const STUDY_WEB_TOOLS = new Set([
  "web_search_knowledge",
  "browse_web_pages",
  "wikipedia_search",
  "mediawiki_search",
  "github_search",
  "stackexchange_search",
]);

function collectWebResults(value: unknown, depth = 0): WebResultItemView[] {
  if (depth > 5) return [];
  if (Array.isArray(value)) return value.flatMap((item) => collectWebResults(item, depth + 1));
  const record = asRecord(value);
  if (!record) return [];

  const url = asString(record.url) ?? asString(record.link) ?? asString(record.href);
  const title = asString(record.title) ?? asString(record.name);
  const own =
    url || title
      ? [
          {
            title: title ?? url ?? "来源",
            ...(url ? { url } : {}),
            ...(asString(record.snippet) ?? asString(record.summary) ?? asString(record.content)
              ? { snippet: asString(record.snippet) ?? asString(record.summary) ?? asString(record.content) }
              : {}),
            ...(asString(record.published_date) ?? asString(record.publishedDate)
              ? { publishedDate: asString(record.published_date) ?? asString(record.publishedDate) }
              : {}),
          },
        ]
      : [];

  const nested = Object.entries(record)
    .filter(([key]) => !["url", "link", "href", "title", "name", "snippet", "summary", "content"].includes(key))
    .flatMap(([, child]) => collectWebResults(child, depth + 1));
  const deduped = new Map<string, WebResultItemView>();
  for (const item of [...own, ...nested]) {
    const key = item.url ?? `${item.title}:${item.snippet ?? ""}`;
    if (!deduped.has(key)) deduped.set(key, item);
  }
  return [...deduped.values()];
}

function collectFileSources(value: unknown, depth = 0): SourceItemView[] {
  if (depth > 4) return [];
  if (Array.isArray(value)) return value.flatMap((item) => collectFileSources(item, depth + 1));
  const record = asRecord(value);
  if (!record) return [];
  const fields = [
    ["md_url", "Markdown 讲义"],
    ["tex_url", "LaTeX 文档"],
    ["pdf_url", "PDF 讲义"],
    ["url", "生成文件"],
  ] as const;
  const own = fields.flatMap(([field, title]) => {
    const url = asString(record[field]);
    return url ? [{ title, url, kind: "file" as const }] : [];
  });
  return [
    ...own,
    ...Object.entries(record)
      .filter(([key]) => !fields.some(([field]) => field === key))
      .flatMap(([, child]) => collectFileSources(child, depth + 1)),
  ];
}

/** 参数 → 结构化键值对；隐藏空字段（undefined/null/空串/空数组/空对象）。 */
export function formatToolArguments(args: unknown): KeyValue[] {
  const record = asRecord(args);
  if (!record) return [];
  const out: KeyValue[] = [];
  for (const [key, raw] of Object.entries(record)) {
    if (raw === undefined || raw === null || raw === "") continue;
    if (Array.isArray(raw) && raw.length === 0) continue;
    if (typeof raw === "object" && !Array.isArray(raw) && Object.keys(raw as object).length === 0) continue;
    const value =
      typeof raw === "string"
        ? raw
        : typeof raw === "number" || typeof raw === "boolean"
          ? String(raw)
          : truncate(JSON.stringify(raw), 300);
    out.push({ key, value });
  }
  return out;
}

/** 工具结果 → 检查器「结果」标签页的领域详情视图。 */
export function adaptToolDetail(name: string, result: unknown, args?: unknown): ToolDetailView {
  const r = asRecord(result);
  const a = asRecord(args);
  if (!r) return { kind: "generic" };

  if (STUDY_WEB_TOOLS.has(name)) {
    const results = collectWebResults(result);
    return {
      kind: "web",
      query:
        asString(a?.query_hint) ??
        asString(a?.query) ??
        asString(a?.topic) ??
        (Array.isArray(a?.knowledge_points) ? asString(a.knowledge_points[0]) : undefined),
      provider: name,
      answer: asString(r.answer) ?? asString(r.summary),
      results,
    };
  }

  switch (name) {
    case "search_questions": {
      const rawItems = Array.isArray(r.questions) ? r.questions : [];
      const items: QuestionItemView[] = rawItems.flatMap((q) => {
        const qr = asRecord(q);
        if (!qr) return [];
        const id = asString(qr.question_id) ?? asString(qr.id);
        if (!id) return [];
        return [
          {
            id,
            stem: asString(qr.stem) ?? asString(qr.stem_html) ?? asString(qr.title),
            difficulty: asString(qr.difficulty),
            knowledge: asStringArray(qr.knowledge),
          },
        ];
      });
      const count = asNumber(r.count) ?? items.length;
      const appliedFilters = formatToolArguments(args).filter(({ key }) => key !== "limit" && key !== "max_pages");
      return { kind: "questions", count, keyword: asString(r.keyword) ?? asString(a?.keyword), items, appliedFilters };
    }

    case "python_scientific_compute": {
      return {
        kind: "compute",
        resultRepr: asString(r.result_repr),
        resultType: asString(r.result_type),
        stdout: asString(r.stdout),
        warnings: asStringArray(r.warnings),
        purpose: asString(a?.purpose),
        code: asString(a?.code),
      };
    }

    case "plot_function": {
      return {
        kind: "plot",
        url: asString(r.url),
        filename: asString(r.filename),
        cached: r.cached === true,
        bytes: asNumber(r.bytes),
      };
    }

    case "web_search": {
      const rawResults = Array.isArray(r.results) ? r.results : [];
      const results: WebResultItemView[] = rawResults.flatMap((item, index) => {
        const ir = asRecord(item);
        if (!ir) return [];
        const title = asString(ir.title) ?? asString(ir.url) ?? `结果 ${index + 1}`;
        return [
          {
            title,
            url: asString(ir.url),
            snippet: asString(ir.snippet),
            publishedDate: asString(ir.published_date),
          },
        ];
      });
      return {
        kind: "web",
        query: asString(r.query),
        provider: asString(r.provider),
        answer: asString(r.answer) ?? asString(r.summary),
        results,
      };
    }

    case "create_paper": {
      return { kind: "paper", paperId: asNumber(r.paper_id), message: asString(r.message) };
    }

    case "get_papers": {
      const rawPapers = Array.isArray(r.papers) ? r.papers : [];
      const papers: KeyValue[] = rawPapers.flatMap((p) => {
        const pr = asRecord(p);
        if (!pr) return [];
        const title = asString(pr.title) ?? asString(pr.paper_name) ?? asString(pr.name);
        const id = asNumber(pr.id) ?? asNumber(pr.paper_id);
        if (!title) return [];
        return [{ key: id !== undefined ? String(id) : title, value: title }];
      });
      const count = asNumber(r.count) ?? papers.length;
      return { kind: "papers", count, papers };
    }

    default:
      return { kind: "generic" };
  }
}

/** 工具结果 → 检查器「来源」标签页的引用列表。 */
export function adaptToolSources(name: string, result: unknown): SourceItemView[] {
  const r = asRecord(result);
  if (!r || r.success === false) return [];

  if (STUDY_WEB_TOOLS.has(name)) {
    return collectWebResults(result)
      .filter((item) => item.url)
      .map((item) => ({
        title: item.title,
        ...(item.url ? { url: item.url } : {}),
        ...(item.snippet ? { snippet: item.snippet } : {}),
        kind: "web" as const,
      }));
  }

  if (["export_study_markdown", "save_markdown_file", "convert_markdown_to_latex", "compile_latex_to_pdf"].includes(name)) {
    const seen = new Set<string>();
    return collectFileSources(result).filter((item) => {
      if (!item.url || seen.has(item.url)) return false;
      seen.add(item.url);
      return true;
    });
  }

  switch (name) {
    case "web_search": {
      const detail = adaptToolDetail("web_search", result);
      if (detail.kind !== "web") return [];
      return detail.results
        .filter((item) => item.url)
        .map((item) => ({ title: item.title, url: item.url, snippet: item.snippet, kind: "web" as const }));
    }

    case "search_questions": {
      const detail = adaptToolDetail("search_questions", result);
      if (detail.kind !== "questions") return [];
      return detail.items.map((item) => ({
        title: `题目 ${item.id}${item.difficulty ? `（${item.difficulty}）` : ""}`,
        snippet: item.knowledge.length > 0 ? `知识点：${item.knowledge.join("、")}` : undefined,
        kind: "question-bank" as const,
      }));
    }

    case "create_paper": {
      const detail = adaptToolDetail("create_paper", result);
      if (detail.kind !== "paper" || detail.paperId === undefined) return [];
      return [
        {
          title: detail.message ?? `试卷 ID: ${detail.paperId}`,
          url: `/papers/${detail.paperId}`,
          kind: "paper" as const,
        },
      ];
    }

    case "plot_function": {
      const detail = adaptToolDetail("plot_function", result);
      if (detail.kind !== "plot" || !detail.url) return [];
      return [{ title: detail.filename ?? "函数图像", url: detail.url, kind: "file" as const }];
    }

    default:
      return [];
  }
}
