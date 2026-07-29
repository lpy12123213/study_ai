/**
 * 续播起始 seq 的判定。
 *
 * 线上问题：退出页面后重新进入时投影是空的（taskId 不同），旧实现一律从 seq 0
 * 全量回放数千条事件，导致「恢复连接」极慢。本地持久化（ACTIVE_RUN_KEY）里其实
 * 存有 lastSeq，应当从上次进度继续。
 */

export interface ResumeAfterSeqInput {
  /** 当前投影正在跟踪的任务（空闲投影为 null）。 */
  currentTaskId: string | null;
  /** 当前投影已处理到的 seq。 */
  currentLastSeq: number;
  /** 本次要恢复的任务。 */
  targetTaskId: string;
  /** localStorage 持久化的该任务进度（可能缺失）。 */
  persistedLastSeq?: number | null;
}

export function resolveResumeAfterSeq(input: ResumeAfterSeqInput): number {
  if (input.currentTaskId && input.currentTaskId === input.targetTaskId) {
    return Math.max(0, input.currentLastSeq);
  }
  return Math.max(0, input.persistedLastSeq ?? 0);
}
