/** 客户端观察耗时 → 可读文案（非服务端权威耗时）。 */
export function formatObservedDuration(ms: number): string {
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)} 秒`;
  return `${Math.round(seconds)} 秒`;
}
