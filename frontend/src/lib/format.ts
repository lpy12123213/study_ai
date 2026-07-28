/**
 * 解析后端时间值。
 * 后端 REST 资源时间戳多为 naive UTC（utcnow_naive().isoformat()，无时区后缀），
 * 而 JS Date 会把无后缀 ISO 串当本地时间解析——这里统一按 UTC 处理；
 * 已带 Z/时区后缀的字符串原样解析。number 一律按 Unix 秒处理。
 */
export function parseBackendDate(value?: string | number | null): Date | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") {
    const d = new Date(value * 1000);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  let s = value.trim();
  if (!s) return null;
  // naive ISO（如 2026-07-21T08:00:00 或 2026-07-21 08:00:00，无 Z/±hh:mm 后缀）按 UTC 解析
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?$/.test(s)) {
    s = s.replace(" ", "T") + "Z";
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? null : d;
}

const dtFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const dFormatter = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

export function formatDateTime(value?: string | number | null): string {
  const d = parseBackendDate(value);
  if (!d) return "—";
  return dtFormatter.format(d);
}

export function formatDate(value?: string | number | null): string {
  const d = parseBackendDate(value);
  if (!d) return "—";
  return dFormatter.format(d);
}

export function formatRelative(value?: string | number | null): string {
  const d = parseBackendDate(value);
  if (!d) return "—";
  const diff = Date.now() - d.getTime();
  const min = Math.floor(diff / 60000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hours = Math.floor(min / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days} 天前`;
  return dFormatter.format(d);
}

export function formatDuration(seconds?: number | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

export function formatBytes(bytes?: number | null): string {
  if (bytes == null || Number.isNaN(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

/** 后端 progress 有的是 0-100，有的是 0-1，统一归一到 0-100。 */
export function normalizeProgress(value?: number | null): number {
  if (value == null || Number.isNaN(value)) return 0;
  const v = value <= 1 && value >= 0 ? value * 100 : value;
  return clamp(v, 0, 100);
}
