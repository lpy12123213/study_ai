import { ComposeRoute } from "@/features/compose/route";

/** 路由层只负责装配；搜题/蓝图组卷/人工审核均位于 feature 内。 */
export function ComposePage() {
  return <ComposeRoute />;
}
