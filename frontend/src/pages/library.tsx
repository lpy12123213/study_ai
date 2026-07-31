import { LibraryRoute } from "@/features/library/route";

/** 路由层只负责装配；题库浏览/AI 出题/抓取评分/预览审核均位于 feature 内。 */
export function LibraryPage() {
  return <LibraryRoute />;
}
