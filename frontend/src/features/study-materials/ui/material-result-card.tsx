import { useState } from "react";
import { BookOpenCheck, ChevronDown, Download, ExternalLink, FileCode2 } from "lucide-react";

import { MarkdownView } from "@/components/markdown/markdown-view";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { downloadUrl } from "@/shared/api/http-client";
import { formatDateTime } from "@/lib/format";
import { STUDY_PRESETS, type StudyMaterialResult } from "@/shared/api/types";
import { cn } from "@/lib/utils";

export function MaterialResultCard({
  result,
  markdown,
  preset,
  latexUrl,
  convertingLatex,
  onConvertLatex,
}: {
  result: StudyMaterialResult;
  markdown: string;
  preset?: string;
  latexUrl?: string;
  convertingLatex: boolean;
  onConvertLatex: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const material = result.material ?? {};
  const mdUrl = material.md_url ?? result.md_url;
  const pdfUrl = material.pdf_url ?? result.pdf_url;
  const texUrl = latexUrl ?? material.tex_url ?? result.tex_url;
  const sections = Array.isArray(material.sections) ? material.sections.length : undefined;
  const presetLabel = STUDY_PRESETS.find((item) => item.value === preset)?.label ?? preset;

  return (
    <article className="overflow-hidden rounded-2xl border border-border bg-card shadow-lift">
      <div className="border-b border-border bg-gradient-to-br from-spectral/5 via-card to-spectral-edge/5 px-5 py-5">
        <div className="text-xs font-semibold text-spectral">讲义已完成</div>
        <h2 className="mt-2 font-display text-2xl font-semibold tracking-tight">
          {material.topic || "学习资料讲义"}
        </h2>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {presetLabel ? <Badge>{presetLabel}</Badge> : null}
          {material.subject ? <Badge variant="muted">{material.subject}</Badge> : null}
          {sections !== undefined ? <Badge variant="outline">{sections} 个知识点</Badge> : null}
          {typeof material.passed === "boolean" ? (
            <Badge variant={material.passed ? "success" : "warning"}>
              {material.passed ? "审查通过" : "仍有质量提示"}
            </Badge>
          ) : null}
        </div>
      </div>

      <div className="px-5 py-5">
        {markdown ? (
          <>
            <div className={cn("relative overflow-hidden", !expanded && "max-h-[31rem]")}>
              <MarkdownView content={markdown} />
              {!expanded ? (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-24 bg-gradient-to-t from-card to-transparent" />
              ) : null}
            </div>
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-spectral hover:underline"
            >
              {expanded ? "收起全文" : "展开阅读全文"}
              <ChevronDown className={cn("size-3.5 transition-transform", expanded && "rotate-180")} />
            </button>
          </>
        ) : (
          <p className="text-sm leading-6 text-muted-foreground">
            该任务已完成并保存到资料档案。当前完成事件未携带 Markdown 正文，可在资料档案中打开成果或下载生成文件。
          </p>
        )}
      </div>

      <div className="flex flex-col gap-3 border-t border-border bg-chrome-surface px-5 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <BookOpenCheck className="size-4 text-tool-success" />
          已自动保存到资料档案
          {material.expires_at ? ` · 下载链接有效期至 ${formatDateTime(material.expires_at)}` : ""}
        </div>
        <div className="flex flex-wrap gap-2">
          {mdUrl ? (
            <Button size="sm" asChild>
              <a href={downloadUrl(mdUrl)} target="_blank" rel="noreferrer">
                <Download /> 下载 Markdown
              </a>
            </Button>
          ) : null}
          {pdfUrl ? (
            <Button variant="outline" size="sm" asChild>
              <a href={downloadUrl(pdfUrl)} target="_blank" rel="noreferrer">
                <Download /> 下载 PDF
              </a>
            </Button>
          ) : null}
          {texUrl ? (
            <Button variant="outline" size="sm" asChild>
              <a href={downloadUrl(texUrl)} target="_blank" rel="noreferrer">
                <ExternalLink /> 下载 LaTeX
              </a>
            </Button>
          ) : markdown ? (
            <Button variant="outline" size="sm" onClick={onConvertLatex} disabled={convertingLatex}>
              <FileCode2 />
              {convertingLatex ? "转换中…" : "转 LaTeX"}
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
