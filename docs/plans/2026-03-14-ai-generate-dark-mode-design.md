# AI 出题工作台暗色模式改造设计

## 背景

`AI 出题工作台` 的视觉定位是 `Editorial AI Studio`（纸感、暖白、强层次）。当前实现中大量使用了写死的浅色渐变与浅色提示块（例如 `rgba(255,255,255,...)`、`bg-blue-50`），在暗色模式下仍保持浅色，从而出现：

- 面板/卡片在暗色下“发白”，对比关系混乱
- 状态提示（蓝色、琥珀色）在暗色下刺眼或反差不足
- 阴影/描边在暗色下层次不明显

## 目标

- 保留现有 `纸感 Editorial` 语言，但为暗色补齐对应的 `midnight parchment` 配色与渐变。
- 不推翻整体结构，不引入新的全局主题体系；只修正局部写死颜色。
- 让暗色下的主舞台（Mission Bar / Generation Stream / Context Rail / Confirmed Shelf）保持一致的层级与质感。

## 方案（选定）

采用“逐组件补齐 dark 版本”的方案：

- 对写死的浅色渐变：为相同元素增加 `dark:bg-[...]` 的暗色渐变。
- 对写死的浅色提示块（蓝色提示、生成中状态）：增加 `dark:` 的 `border/bg/text` 组合。
- 对写死的浅色阴影：在暗色下换成更合适的阴影（更深、透明度更低）。

不改变全局 `--color-*` 变量（避免影响全站），只在 `aiGenerate` 页面内做适配。

## 视觉方向

暗色模式保持“夜间纸面”氛围：

- 页面底：深石墨/深蓝灰为主，顶部保留轻微蓝色光晕，辅以非常弱的暖色光斑。
- 面板/卡片：比页面底更亮一阶，带轻微纵向渐变，边界用 `border-border` 控制。
- 状态色：蓝色改为更沉的 `sky` 系，琥珀/红色在暗色下减少刺眼感。

## 涉及文件（预期修改点）

- `frontend/src/pages/aiGenerate/AiGenerateStudioPage.tsx`
  - 页面背景渐变 + Generation Stream 卡片背景/阴影 + “生成中”蓝色 pill
- `frontend/src/pages/aiGenerate/MissionComposer.tsx`
  - Mission Bar 渐变 + 输入框内阴影 + LaTeX 规范提示块
- `frontend/src/pages/aiGenerate/ContextRail.tsx`
  - 侧栏卡片渐变 + 图标底色（amber）
- `frontend/src/pages/aiGenerate/QuestionDraftCard.tsx`
  - 卡片渐变 + 阴影
- `frontend/src/pages/aiGenerate/ArtifactSection.tsx`
  - LaTeX Preview 渐变 + streaming 状态色 + 已编辑提示色
- `frontend/src/pages/aiGenerate/ConfirmedShelf.tsx`
  - 卡片渐变 + 阴影

## 验收标准

- 暗色模式下页面不出现大面积“亮白”面板；主背景、面板、卡片层级清晰。
- 蓝色/琥珀色提示在暗色下不过曝，文字可读。
- 生成中/失败/完成等状态在暗色下仍能一眼分辨。

