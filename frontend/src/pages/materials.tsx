import { StudyMaterialsRoute } from "@/features/study-materials/route";

/** 路由层只负责装配；资料生成契约、投影、连接与 UI 均位于 feature 内。 */
export function MaterialsPage() {
  return <StudyMaterialsRoute />;
}
