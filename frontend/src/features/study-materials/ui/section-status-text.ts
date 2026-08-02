/** 后端 section_fill 状态词表（author/fill.py）：start|ok|retry|failed。 */
export function sectionStatusText(status: string): string {
  switch (status) {
    case "start":
      return "撰写中";
    case "ok":
      return "已完成";
    case "retry":
      return "重试中";
    case "failed":
      return "失败";
    default:
      return status;
  }
}
