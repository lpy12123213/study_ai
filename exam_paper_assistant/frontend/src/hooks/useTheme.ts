import { useEffect } from "react";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";

export type ThemeMode = "light" | "dark";

export function useTheme() {
  const [theme, setTheme] = useLocalStorageState<ThemeMode>("epa_theme", "light");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);

  const toggle = () => {
    setTheme(theme === "dark" ? "light" : "dark");
  };

  return { theme, setTheme, toggle };
}

