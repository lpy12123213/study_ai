import { Link } from "react-router";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-muted text-muted-foreground">
        <Compass className="size-7" />
      </div>
      <div>
        <div className="text-2xl font-semibold tracking-tight">404</div>
        <p className="mt-1 text-sm text-muted-foreground">页面不存在或已被移动</p>
      </div>
      <Button asChild variant="outline">
        <Link to="/">返回工作台</Link>
      </Button>
    </div>
  );
}
