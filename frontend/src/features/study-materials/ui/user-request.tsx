import { Badge } from "@/components/ui/badge";
import { STUDY_PRESETS } from "@/shared/api/types";

export function StudyMaterialsUserRequest({
  query,
  subject,
  preset,
  withQuestions,
  withDiagrams,
  extraTools,
}: {
  query: string;
  subject?: string;
  preset?: string;
  withQuestions?: boolean;
  withDiagrams?: boolean;
  extraTools?: boolean;
}) {
  const presetLabel = STUDY_PRESETS.find((item) => item.value === preset)?.label ?? preset;
  return (
    <div className="flex flex-col items-end gap-2">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-xl rounded-br-md bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground shadow-soft">
        {query}
      </div>
      <div className="flex max-w-[90%] flex-wrap justify-end gap-1.5">
        {subject ? <Badge variant="outline">{subject}</Badge> : null}
        {presetLabel ? <Badge variant="outline">{presetLabel}</Badge> : null}
        {withQuestions ? <Badge variant="outline">含练习题</Badge> : null}
        {withDiagrams ? <Badge variant="outline">含示意图</Badge> : null}
        {extraTools ? <Badge variant="outline">扩展来源</Badge> : null}
      </div>
    </div>
  );
}
