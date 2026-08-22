# 物理、化学高考真题隔离区建设计划

本计划对应本地题库的物理、化学高考真题区域。题目、出处、原始文档和 SVG 侧车保存在被 `.gitignore` 忽略的 `.local/`；本次导入不修改应用代码。

## 数据建设状态

- 目标年度：2007–2026；`question_cache.subject` 使用 `物理`、`化学`，每题同时写入 `gaokao_question_sources`。
- 当前数据库快照：物理 1,003 题、化学 1,895 题；两科每题均有来源记录，年份均覆盖 2007–2026。
- 已合并题源：`rainewhk/gaokao` 文字题、`GAOKAO-MM` 选择题与图片、GaokaoHub 活动页面、2007 新浪视觉题页、学业规划平台单科文档。
- 图形：题面引用统一改为 `/api/media/generated/<filename>.svg`；SVG 是内嵌原始栅格/原始格式容器，保留来源映射，不宣称完成路径级矢量重绘。
- 来源核验：当前 `verified=0`，答案/解析按来源保留，未人工臆造缺失答案。

## 前端建设计划

1. 在题库导航中增加“高考真题 / 物理 / 化学”隔离入口，筛选项包含年份、地区、卷名、题源与题号。
2. 列表卡片展示出处徽标、来源链接、核验状态和图形数量；对 `gaokao_visual_range` 显式显示“视觉区间题”，避免把视觉页误当作 OCR 文本。
3. 题面渲染沿用现有生成媒体地址，SVG 图形支持放大、原图查看和来源回链；缺图时显示来源状态，不替换为占位图形。
4. 导入任务页展示抓取/手动导入的逐卷进度、答案缺失、图形转换失败和待恢复清单；不得把未抓取的禁用条目显示为已完成。
5. 来源详情页按 `source_url + source_file + question_number` 展示出处链，允许同题号的不同来源并列，不做无来源的去重合并。

## 可复核报告

- `.local/imports/gaokao-physics-chemistry-final-coverage-report.json`
- `.local/imports/gaokaohub-source/gaokao-science-pages-import-report.json`
- `.local/imports/gaokaohub-source/science-figure-svg-manifest.json`
- `.local/imports/gaokaohub-source/sitemap-science-inventory.json`
- `.local/imports/gaokao-2007-source/sina-visual-import-report.json`
- `.local/imports/xueyeguihua-source/fetch-report.json`
- `.local/imports/xueyeguihua-source/question-import-report.json`
- `.local/imports/gaokao-physics-chemistry-final-audit.json`

## 已知缺口与后续验收

- GaokaoHub 仍有 135 个无公开链接的禁用地方卷条目（物理 100、化学 35），须补齐可下载来源后再标记完成。
- 学业规划平台的 22 份理综合卷已留存原始文档，但尚未可靠拆分为物理/化学题号；不能计入两科逐题覆盖。
- 2007 新浪条目为题号区间视觉题，答案以本地答案图保存；需后续 OCR/人工校验时才可变为逐题文本答案。
- 验收命令至少包括 `PRAGMA integrity_check`、按科目/年份/来源统计、来源 URL 非空检查、SVG 文件存在性检查和逐卷预期题号对照。
