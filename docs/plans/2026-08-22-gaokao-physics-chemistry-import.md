# 物理、化学高考真题隔离区建设计划

本计划对应本地题库的物理、化学高考真题区域。题目、出处、原始文档和 SVG 侧车保存在被 `.gitignore` 忽略的 `.local/`；本次导入不修改应用代码。

## 数据建设状态

- 目标年度：2007–2026；`question_cache.subject` 以 `物理`、`化学` 为隔离标签，并兼容已有 `physics`、`chemistry` 别名，每题同时写入 `gaokao_question_sources`。
- 当前数据库快照：物理 1,218 题、化学 2,063 题；两科每题均有来源记录，年份均覆盖 2007–2026。答案非空分别为 766、1,622，仍全部标记为未核验。
- 已合并题源：`rainewhk/gaokao` 文字题、`GAOKAO-MM` 选择题与图片、GaokaoHub 活动页面、GaokaoHub 禁用卡片/公开别名中经页面身份校验恢复的 33 个页面（新增物理 54、化学 27；其中 32 个对应禁用清单条目）、2007 新浪视觉题页、学业规划平台单科文档、8 份可解析理综 DOCX 的分科拆分（新增物理 106、化学 94），以及中国教育在线 EOL 在 2016–2018、2020–2021 目录中身份校验通过的 38 个地方/省份卷视觉页（物理 19、化学 19）和 2022–2024 目录中身份校验通过的 64 个地方/省份卷视觉页（物理 36、化学 28）。恢复页面只代表站点列出的题卡，来源备注标记为 `site_listed_count_only`，不宣称为完整试卷；EOL 卷标记为 `visual_page_range_only`。
- 图形：题面引用统一改为 `/api/media/generated/<filename>.svg`；当前物理/化学题面和答案共有 2,691 个本地 SVG 引用（2,143 个唯一文件），均已注册且文件存在。EOL 2016–2021 视觉卷新增 95 个 SVG 侧车并复用 1 个，题面 76 张、答案 20 张；EOL 2022–2024 视觉卷新增 126 个 SVG 侧车（题面 86 张、答案 63 张）；本轮又将 3 道化学题中的 11 个残留远程图片转为本地 SVG。SVG 是内嵌原始栅格/原始格式容器，保留来源映射，不宣称完成路径级矢量重绘。
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
- `.local/imports/gaokaohub-source/disabled-candidate-probe.json`
- `.local/imports/gaokaohub-source/disabled-recovered-fetch-report.json`
- `.local/imports/gaokaohub-source/disabled-recovered-import-report.json`
- `.local/imports/gaokaohub-source/disabled-expanded-candidate-probe.json`
- `.local/imports/gaokaohub-source/disabled-expanded-recovered-fetch-report.json`
- `.local/imports/gaokaohub-source/disabled-expanded-recovered-import-report.json`
- `.local/imports/gaokaohub-source/science-figure-svg-manifest.json`
- `.local/imports/gaokaohub-source/sitemap-science-inventory.json`
- `.local/imports/gaokao-2007-source/sina-visual-import-report.json`
- `.local/imports/xueyeguihua-source/fetch-report.json`
- `.local/imports/xueyeguihua-source/question-import-report.json`
- `.local/imports/xueyeguihua-source/combined-science-import-report.json`
- `.local/imports/xuebake-physics-retrieval-audit.json`
- `.local/imports/gaokao-physics-chemistry-final-audit.json`
- `.local/imports/eol-gaokao-source-inventory.json`
- `.local/imports/eol-gaokao-source/fetch-report.json`
- `.local/imports/eol-gaokao-source/image-fetch-report.json`
- `.local/imports/eol-gaokao-source/image-svg-manifest.json`
- `.local/imports/eol-gaokao-source/visual-import-report.json`
- `.local/imports/eol-gaokao-source/legacy/legacy-source-inventory.json`
- `.local/imports/eol-gaokao-source/legacy/legacy-fetch-report.json`
- `.local/imports/eol-gaokao-source/legacy/legacy-image-fetch-report.json`
- `.local/imports/eol-gaokao-source/legacy/legacy-image-svg-manifest.json`
- `.local/imports/eol-gaokao-source/legacy/legacy-visual-import-report.json`
- `.local/imports/gaokaohub-source/remote-science-svg-repair-report.json`

## 已知缺口与后续验收

- GaokaoHub 禁用清单仍有 103 个条目没有匹配到公开页面（物理 75、化学 28）；已恢复的 33 个页面仅导入站点列出的题卡，须补齐可下载来源和逐卷题号后才能标记完整。
- 学业规划平台的 22 份理综合卷中，8 份 DOCX 已按各卷题号规则拆入 200 行（物理 106、化学 94）；其余 14 份 OLE/DOCX 仍仅保留原始文档，且组合卷没有答案文档，不能将其宣称为答案已核验。
- 2020 全国卷1的物理 11、19 和化学 13、19 为 `visual_only`，物理 24 为 `partial_text`；原图均已转为本地 SVG，待后续人工/OCR 校验题面。
- 学业规划平台另有 10 个单科 HTML/error 响应；Xuebake 物理合集页面没有资源 ID 或直链，下载流程受登录/站点验证阻断，均保留在报告中而不冒充已导入。
- 2007 新浪条目为题号区间视觉题，答案以本地答案图保存；需后续 OCR/人工校验时才可变为逐题文本答案。
- EOL 目录共列出 94 个候选入口，其中 64 个通过年份、地区、科目一致性校验后导入；这些记录保留整页题图和可匹配的答案图，不冒充逐题 OCR。其余 30 个错链或身份不一致入口保留在抓取报告中。
- EOL 2016–2018、2020–2021 目录另有 38 个入口通过同样校验并导入；其中 2020 年答案链接无法独立校验的记录保留空答案，不把题面图冒充答案。
- GaokaoHub 禁用清单的 103 条未匹配统计与 EOL 的 64 个视觉页是独立来源口径，尚未逐卷去重闭合；因此当前仍不能宣称“所有地方卷”已完成。
- 验收命令至少包括 `PRAGMA integrity_check`、按科目/年份/来源统计、来源 URL 非空检查、SVG 文件存在性检查和逐卷预期题号对照。
