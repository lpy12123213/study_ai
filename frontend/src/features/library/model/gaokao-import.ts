import type { GaokaoQuestionImportItem } from "@/features/question-library/api";

export interface GaokaoImportIssue {
  index: number;
  field: string;
  message: string;
}

export interface GaokaoImportPreflight {
  candidates: Record<string, unknown>[];
  validItems: GaokaoQuestionImportItem[];
  issues: GaokaoImportIssue[];
}

export function parseGaokaoImportText(raw: string): Record<string, unknown>[] {
  const text = raw.trim();
  if (!text) return [];
  const parsed: unknown = JSON.parse(text);
  const items = Array.isArray(parsed)
    ? parsed
    : parsed && typeof parsed === "object" && Array.isArray((parsed as { items?: unknown }).items)
      ? (parsed as { items: unknown[] }).items
      : null;
  if (!items) throw new Error("JSON 顶层必须是题目数组，或包含 items 数组。");
  return items.map((item) => (item && typeof item === "object" ? (item as Record<string, unknown>) : {}));
}

function requiredText(value: unknown): string {
  return String(value ?? "").trim();
}

export function preflightGaokaoImport(candidates: Record<string, unknown>[]): GaokaoImportPreflight {
  const issues: GaokaoImportIssue[] = [];
  const validItems: GaokaoQuestionImportItem[] = [];
  const seen = new Set<string>();

  candidates.forEach((candidate, index) => {
    const entryIssues: GaokaoImportIssue[] = [];
    const questionId = requiredText(candidate.question_id);
    const subject = requiredText(candidate.subject);
    const stem = requiredText(candidate.stem);
    const source = candidate.source && typeof candidate.source === "object"
      ? (candidate.source as Record<string, unknown>)
      : {};
    const region = requiredText(source.region);
    const paperName = requiredText(source.paper_name);
    const examYear = Number(source.exam_year);

    const addIssue = (field: string, message: string) => entryIssues.push({ index, field, message });
    if (!questionId) addIssue("question_id", "缺少 question_id");
    else if (seen.has(questionId)) addIssue("question_id", `question_id ${questionId} 重复`);
    if (!subject) addIssue("subject", "缺少学科");
    if (!stem) addIssue("stem", "缺少题干");
    if (!Number.isInteger(examYear) || examYear < 1952 || examYear > 2100) {
      addIssue("source.exam_year", "年份必须在 1952–2100 之间");
    }
    if (!region) addIssue("source.region", "缺少地区");
    if (!paperName) addIssue("source.paper_name", "缺少试卷名");
    if (questionId) seen.add(questionId);

    issues.push(...entryIssues);
    if (entryIssues.length > 0) return;

    validItems.push({
      question_id: questionId,
      subject,
      stem,
      answer: requiredText(candidate.answer) || undefined,
      analysis: requiredText(candidate.analysis) || undefined,
      question_type: requiredText(candidate.question_type) || undefined,
      difficulty: requiredText(candidate.difficulty) || undefined,
      difficulty_value:
        candidate.difficulty_value === null || candidate.difficulty_value === undefined
          ? undefined
          : Number(candidate.difficulty_value),
      knowledge_point: requiredText(candidate.knowledge_point) || undefined,
      knowledge_points: Array.isArray(candidate.knowledge_points)
        ? candidate.knowledge_points.map(requiredText).filter(Boolean)
        : undefined,
      origin: candidate.origin === "crawled" ? "crawled" : "media",
      source: {
        exam_year: examYear,
        region,
        paper_name: paperName,
        paper_variant: requiredText(source.paper_variant) || undefined,
        question_number: requiredText(source.question_number) || undefined,
        source_url: requiredText(source.source_url) || undefined,
        source_note: requiredText(source.source_note) || undefined,
        verified: Boolean(source.verified),
      },
    });
  });

  return { candidates, validItems, issues };
}
