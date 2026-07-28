import { Badge } from "@/components/ui/badge";

const DIFFICULTY_VARIANT: Record<string, "success" | "warning" | "destructive" | "muted"> = {
  简单: "success",
  容易: "success",
  中等: "warning",
  适中: "warning",
  困难: "destructive",
  难: "destructive",
};

export function DifficultyBadge({ difficulty, className }: { difficulty?: string | null; className?: string }) {
  if (!difficulty) return null;
  return (
    <Badge variant={DIFFICULTY_VARIANT[difficulty] ?? "muted"} className={className}>
      {difficulty}
    </Badge>
  );
}
