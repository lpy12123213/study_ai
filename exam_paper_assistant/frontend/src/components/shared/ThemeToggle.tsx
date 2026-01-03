import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/useTheme";

export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const Icon = theme === "dark" ? Sun : Moon;

  return (
    <Button
      type="button"
      variant="ghost"
      className="w-full justify-start gap-2"
      onClick={toggle}
      title="切换主题"
    >
      <Icon className="h-4 w-4" />
      {theme === "dark" ? "浅色模式" : "深色模式"}
    </Button>
  );
}
