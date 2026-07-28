/**
 * URL 搜索参数解析与更新（架构 §8.4）。
 * URL 是可分享/可恢复页面状态（filter/page/tab/selectedId）的唯一所有者；
 * 解码必须经显式解析函数，不直接信任字符串。
 */

export function parseStringParam(params: URLSearchParams, key: string): string | undefined {
  const value = (params.get(key) ?? "").trim();
  return value ? value : undefined;
}

export function parseIntParam(
  params: URLSearchParams,
  key: string,
  opts?: { min?: number; max?: number },
): number | undefined {
  const raw = (params.get(key) ?? "").trim();
  if (!raw || !/^-?\d+$/.test(raw)) return undefined;
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) return undefined;
  if (opts?.min !== undefined && value < opts.min) return undefined;
  if (opts?.max !== undefined && value > opts.max) return undefined;
  return value;
}

export function parseEnumParam<T extends string>(
  params: URLSearchParams,
  key: string,
  allowed: readonly T[],
): T | undefined {
  const raw = (params.get(key) ?? "").trim();
  return (allowed as readonly string[]).includes(raw) ? (raw as T) : undefined;
}

export function parseBoolParam(params: URLSearchParams, key: string): boolean | undefined {
  const raw = (params.get(key) ?? "").trim();
  if (raw === "1" || raw === "true") return true;
  if (raw === "0" || raw === "false") return false;
  return undefined;
}

/**
 * 生成新的 URLSearchParams：patch 中 null/undefined/空串表示删除该键。
 * 与 setSearchParams(..., { replace: true }) 搭配用于筛选变更（不产生历史条目）。
 */
export function updateSearchParams(
  prev: URLSearchParams,
  patch: Record<string, string | number | boolean | null | undefined>,
): URLSearchParams {
  const next = new URLSearchParams(prev);
  for (const [key, value] of Object.entries(patch)) {
    if (value === null || value === undefined || value === "") {
      next.delete(key);
    } else {
      next.set(key, String(value));
    }
  }
  return next;
}
