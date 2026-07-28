import { PencilLine } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { STUDY_PRESETS } from "@/shared/api/types";

export function StudyMaterialsUserRequest({
  query,
  subject,
  preset,
  requirements,
  withQuestions,
  withDiagrams,
  extraTools,
  preferLocalArchive,
  maxPoints,
  onEditRerun,
}: {
  query: string;
  subject?: string;
  preset?: string;
  requirements?: string;
  withQuestions?: boolean;
  withDiagrams?: boolean;
  extraTools?: boolean;
  preferLocalArchive?: boolean;
  maxPoints?: number;
  /** 「编辑并重跑」：把本次请求参数回填到输入舱。 */
  onEditRerun?: () => void;
}) {
  const presetLabel = STUDY_PRESETS.find((item) => item.value === preset)?.label ?? preset;
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground shadow-soft">
        {query}
      </div>
      <div className="flex max-w-[90%] flex-wrap items-center justify-end gap-1.5">
        {subject ? <Badge variant="outline">{subject}</Badge> : null}
        {presetLabel ? <Badge variant="outline">{presetLabel}</Badge> : null}
        {withQuestions ? <Badge variant="outline">含练习题</Badge> : null}
        {withDiagrams ? <Badge variant="outline">含示意图</Badge> : null}
        {extraTools ? <Badge variant="outline">扩展来源</Badge> : null}
        {preferLocalArchive ? <Badge variant="outline">优先本地档案</Badge> : null}
        {maxPoints !== undefined ? <Badge variant="outline">最多 {maxPoints} 个知识点</Badge> : null}
        {requirements ? (
          <Badge variant="outline" className="max-w-72">
            <span className="truncate">要求：{requirements}</span>
          </Badge>
        ) : null}
        {onEditRerun ? (
          <button
            type="button"
            onClick={onEditRerun}
            className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            <PencilLine className="size-3" />
            编辑并重跑
          </button>
        ) : null}
      </div>
    </div>
  );
}
