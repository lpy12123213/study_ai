# 物理、化学高考真题隔离区建设计划

本计划对应本地题库的物理、化学高考真题区域。题目、出处、原始文档和 SVG 侧车保存在被 `.gitignore` 忽略的 `.local/`；本次导入不修改应用代码。

## 数据建设状态

- 目标年度：2007–2026；`question_cache.subject` 以 `物理`、`化学` 为隔离标签，并兼容已有 `physics`、`chemistry` 别名，每题同时写入 `gaokao_question_sources`。
- 当前数据库快照：物理 1,712 题、化学 2,451 题；两科每题均有来源记录，年份均覆盖 2007–2026。答案非空分别为 1,041、1,941，仍全部标记为未核验。
- 已合并题源：`rainewhk/gaokao` 文字题、`GAOKAO-MM` 选择题与图片、GaokaoHub 活动页面、GaokaoHub 禁用卡片/公开别名中经页面身份校验恢复的 33 个页面（新增物理 54、化学 27；其中 32 个对应禁用清单条目）、2007 新浪视觉题页、学业规划平台单科文档、8 份可解析理综 DOCX 的分科拆分（新增物理 106、化学 94），中国教育在线 EOL 2015 年 5 个可访问视觉页（物理 2、化学 3）、2016–2018、2020–2021 目录中身份校验通过的 38 个地方/省份卷视觉页（物理 19、化学 19）、2022–2024 目录中身份校验通过的 64 个地方/省份卷视觉页（物理 36、化学 28），以及 2023 年 10 套物理合订 PDF（浙江 1 月/6 月、全国甲/乙/新课标、江苏、湖南、湖北、辽宁、山东，新增物理 169）。恢复页面只代表站点列出的题卡，来源备注标记为 `site_listed_count_only`，不宣称为完整试卷；EOL 卷标记为 `visual_page_range_only`；2023 PDF 批次标记为 `question_text_extracted_unverified`。
- 图形：题面和答案共有 3,825 个本地 SVG 引用（2,810 个唯一文件），另有 6,991 个已登记 SVG 侧车，均已注册、哈希/大小一致且文件存在；远程 `<img src>` 为 0。EOL 2015 新增 9 个 SVG 侧车（题面 5 张、答案 4 张）；EOL 2016–2021 视觉卷新增 95 个 SVG 侧车并复用 1 个，题面 76 张、答案 20 张；EOL 2022–2024 视觉卷新增 126 个 SVG 侧车（题面 86 张、答案 63 张）；另有 3 道化学题的 11 个残留远程图片已转为本地 SVG；2023 PDF 批次新增 81 个整页 SVG 侧车，题目引用 239 次；2023 化学 PDF 新增 29 个整页 SVG 侧车；本轮 2018–2019 正式 PDF/视觉预览/DOCX/OLE 图形批次新增 402 个 SVG 侧车；本轮 2024 新课标理综整卷新增 19 个整页 SVG 侧车，物理/化学题目引用 33 次；本轮 2021 全国甲卷新增 24 个整页/答案页 SVG 侧车；本轮 2025 单科 DOCX 批次新增 473 个 PNG→SVG 侧车，物理/化学题目引用 565 次。SVG 是内嵌原始栅格/原始格式容器，保留来源映射，不宣称完成路径级矢量重绘。
- 2023 化学原卷补充：浙江卷 21 题、江苏卷 17 题，共 38 题，来源文件与 SHA-256 记录在 `.local/imports/gaokao-2023-chemistry-pdfs/import-report.json`；两份 PDF 共生成 29 个整页 SVG 侧车。江苏卷客观题答案仅作文字摘录，主观题答案保留参考答案页 SVG；全部标记为未核验。
- 本轮正式来源补充共 276 题（物理 124、化学 152）：除既有 2018 江苏物理/化学、2017 全国卷 1/3、2019 北京/全国卷 2/全国卷 3/全国卷 1 化学/江苏化学/江苏物理批次外，新增 2019 海南卷化学 19 题、2019 天津卷理综物理 12 题/化学 10 题，以及 2024 新课标卷理科综合物理 13 题/化学 11 题。2024 批次使用 `.local/imports/xueyeguihua-source/files/2024_26_6.bin` 与整卷 PDF `external-2024-newstandard-full.pdf`，物理题 14–26、化学题 7–13/27–30 按原卷题号导入，19 个整页 PDF 页面封装为本地 SVG；化学第 27 题沉淀 pH 表显式转为 LaTeX `array`。所有 MathType 占位符均保留 LaTeX 视觉回退，不从 GaokaoHub 乱码或缺失字段猜测。
- 2021 全国甲卷补充导入 26 题（物理 14、化学 12）：物理题 14–25、33–34，化学题 7–13、26–28、35–36，题号与 OLE 综合卷分段交叉核对；物理 DOCX 原卷页 1–4、化学 DOCX 原卷页 1–6/答案页 8 封装为本地 SVG。物理第 22、23 题和化学第 9 题的数据表显式写为 LaTeX `array`；其余 MathType/结构式/装置图保留 `\(\text{原卷公式见本题SVG}\)` 或 `\(\text{原卷图形见本题SVG}\)` 回退。化学第 35 题在公开题面 DOCX 中缺少原题页，采用独立来源页面题号 11（对应综合卷第 35 题）及答案页 8 SVG，并在来源备注中标注，未将其标记为已核验。来源：物理原卷 [PDF](https://24799959.s21i.faiusr.com/61/ABUIABA9GAAgwovmpgYonunpiAI.pdf)、物理解析 [21cnjy](https://zy.21cnjy.com/23357442)、化学解析/原题页 [21cnjy](https://zy.21cnjy.com/12851813)、公开文档索引 [金榜题名](https://jhgk.cn/trendDetails.htm?id=54a14cc7-f2f3-4ee6-a1fd-b2b55f952f0d)。GaokaoHub 仅作索引，不采信其乱码正文。
- 2025 年单科地方/区域卷补充导入 368 题（物理 185、化学 183）：按原卷 DOCX 去重后纳入北京、江苏、海南（仅物理）、山东、云南、广东、河北、甘肃、河南、四川，以及黑龙江/吉林/辽宁/内蒙古合卷、陕西/山西/宁夏/青海合卷，共 22 份可核验原卷文件。重复字节的纸型 35/36/37 与 25、39/40/41 与 38 作为来源别名记录，不重复生成题目。题干中的 WMF/PNG 图形均引用本地 SVG；文字层未可靠还原的公式保留 LaTeX 视觉回退，表格线索追加 LaTeX `array` 视觉回退。答案面板按 DOCX 可读内容摘录，缺失部分保留答案页 SVG 提示，全部标记为未核验；不从 GaokaoHub 乱码正文取题面。索引来源为 [学业规划历年真题目录](https://www.xueyeguihua.com/exam/trueexam/year/2025.html)。
- 公式/表格硬规则：新导入题面不把 PDF Symbol 字体的上标、电荷、箭头或结构式乱码当作公式写入；可可靠识别的文字只使用 LaTeX 分隔符，无法可靠还原的公式或表格写成 LaTeX 视觉来源提示并保留原页 SVG。GaokaoHub 历史卡片已将 `$...$`/`$$...$$` 统一为 `\(...\)`/`\[...\]`，3 个 HTML 表格转为 LaTeX `array`，私有区乱码清除；仍有 748 条含未可靠公式候选的卡片标记 `gaokaohub_latex_pending_visual_review`，原始字段保存在 `.local/imports/gaokaohub-source/gaokaohub-latex-originals.json`。
- 2019 海南化学 OLE 的 MathType/图形占位符全部保留为 `\(\text{原卷公式见本题SVG}\)` 或 `\(\text{原卷图形见本题SVG}\)`，不从乱码猜公式；第 14 题的时间–浓度表已显式转为 LaTeX `\begin{array}`，原卷页 SVG 仍作为视觉依据。2019 天津卷 OLE 的 MathType/图形占位符沿用同一策略，化学第 2 题离子方程式表已显式转为 LaTeX `\begin{array}`，装置/数据表保留原卷 SVG；2019 全国卷 3 也沿用同一策略；2019 全国卷 1 的扫描 PDF 存在物理页重复/缺失，因此只导入有完整可读文本与图形映射的化学题，物理部分保留缺口。
- 全库规范化审计已覆盖两科 4,163 行：`rainewhk/gaokao`、GAOKAO-MM 的 `$...$` 已改为 `\(...\)`/`\[...\]`；2023 合订 PDF、2024 新课标整卷、2021 全国甲卷、2025 单科 DOCX 与 OLE/DOCX 文本的私有区/控制字形已映射为明确运算符或 `\(\text{原卷符号见SVG}\)`。原始字段保存在 `.local/imports/science-latex-originals.json`，报告为 `.local/imports/science-latex-normalization-report.json`；审计结果为美元符号、私有区字符、HTML 表格、替换字符和残留 EMBED 控制串均为 0。
- 对仍无法从文字层可靠分列的 96 行表格线索，已追加或保留 LaTeX `array` 视觉/来源回退并标记 `table_visual_review_required`；2019 海南第 14 题的表格为已分列的 LaTeX `array`，不臆造其余单元格，报告为 `.local/imports/science-table-latex-fallback-report.json`。
- 来源核验：当前 `verified=0`，答案/解析按来源保留，未人工臆造缺失答案。

## 前端建设计划

1. 在题库导航中增加“高考真题 / 物理 / 化学”隔离入口，筛选项包含年份、地区、卷名、题源与题号。
2. 列表卡片展示出处徽标、来源链接、核验状态和图形数量；对 `gaokao_visual_range` 显式显示“视觉区间题”，避免把视觉页误当作 OCR 文本。
3. 题面渲染沿用现有生成媒体地址，SVG 图形支持放大、原图查看和来源回链；缺图时显示来源状态，不替换为占位图形。
4. 导入任务页展示抓取/手动导入的逐卷进度、答案缺失、图形转换失败和待恢复清单；不得把未抓取的禁用条目显示为已完成。
5. 来源详情页按 `source_url + source_file + question_number` 展示出处链，允许同题号的不同来源并列，不做无来源的去重合并。

6. 导入接口沿用统一任务中心并在 `docs/API.md` 固化契约：爬取使用 `POST /api/question-library/gaokao/crawl`（SSE）或 `POST /api/tasks/question-library/gaokao-crawl`（任务句柄），手动批量导入使用 `POST /api/question-library/gaokao/items/manual-import`；两者均要求年份、地区、卷名、题号和出处字段，图形必须走本地 SVG 媒体登记，答案缺失和转换失败在进度事件中显式呈现。代码冻结期间只补数据与文档，不改应用实现。

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
- `.local/imports/xueyeguihua-source/import-2017-national1-report.json`
- `.local/imports/xueyeguihua-source/import-2017-national3-report.json`
- `.local/imports/xueyeguihua-source/import-2019-beijing-report.json`
- `.local/imports/xueyeguihua-source/import-2019-national1-chemistry-report.json`
- `.local/imports/xueyeguihua-source/import-2019-national2-report.json`
- `.local/imports/xueyeguihua-source/import-2019-national3-report.json`
- `.local/imports/xueyeguihua-source/import-2019-jiangsu-chemistry-report.json`
- `.local/imports/xueyeguihua-source/import-2019-jiangsu-physics-report.json`
- `.local/imports/xueyeguihua-source/import-2018-jiangsu-physics-report.json`
- `.local/imports/xueyeguihua-source/import-2018-jiangsu-chemistry-report.json`
- `.local/imports/xueyeguihua-source/import-2019-hainan-chemistry-report.json`
- `.local/imports/xueyeguihua-source/import-2024-newstandard-physics-chemistry-report.json`
- `.local/imports/xueyeguihua-source/import-2021-nationalA-physics-chemistry-report.json`
- `.local/imports/xueyeguihua-source/import_2021_nationalA_physics_chemistry_docx_ole.py`
- `.local/imports/xueyeguihua-source/import-2025-xueyeguihua-docx-report.json`
- `.local/imports/xueyeguihua-source/import_2025_xueyeguihua_docx.py`
- `.local/imports/xueyeguihua-source/import_2024_newstandard_physics_chemistry_pdf.py`
- `.local/imports/xueyeguihua-source/import_2019_national3_ole_scan.py`
- `.local/imports/xueyeguihua-source/import_2019_jiangsu_physics_preview.py`
- `.local/imports/xueyeguihua-source/import_2018_jiangsu_physics_pdf.py`
- `.local/imports/xueyeguihua-source/import_2018_jiangsu_chemistry_docx.py`
- `.local/imports/xueyeguihua-source/import_2019_hainan_chemistry_ole.py`
- `.local/imports/gaokao-2023-physics-10/import-report.json`
- `.local/imports/gaokao-2023-physics-10/source-inventory.json`
- `.local/imports/gaokao-2023-chemistry-pdfs/import-report.json`
- `.local/imports/gaokaohub-source/gaokaohub-latex-encoding-audit.json`
- `.local/imports/gaokaohub-source/gaokaohub-latex-originals.json`
- `.local/imports/science-latex-normalization-report.json`
- `.local/imports/science-latex-originals.json`
- `.local/imports/science-table-latex-fallback-report.json`
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
- `.local/imports/eol-gaokao-source/legacy2015/legacy2015-source-inventory.json`
- `.local/imports/eol-gaokao-source/legacy2015/legacy2015-fetch-report.json`
- `.local/imports/eol-gaokao-source/legacy2015/legacy2015-image-fetch-report.json`
- `.local/imports/eol-gaokao-source/legacy2015/legacy2015-image-svg-manifest.json`
- `.local/imports/eol-gaokao-source/legacy2015/legacy2015-visual-import-report.json`
- `.local/imports/gaokaohub-source/remote-science-svg-repair-report.json`

## 已知缺口与后续验收

- GaokaoHub 禁用清单仍有 103 个条目没有匹配到公开页面（物理 75、化学 28）；已恢复的 33 个页面仅导入站点列出的题卡，须补齐可下载来源和逐卷题号后才能标记完整。
- 学业规划平台的 22 份理综合卷中，8 份 DOCX 已按各卷题号规则拆入 200 行（物理 106、化学 94）；2019 全国卷 3 另经完整扫描 PDF + OLE MathType 复核补入 26 行，原始清单中仍有 13 份 OLE/DOCX 仅保留原始文档，且组合卷没有答案文档，不能将其宣称为答案已核验。
- 2020 全国卷1的物理 11、19 和化学 13、19 为 `visual_only`，物理 24 为 `partial_text`；原图均已转为本地 SVG，待后续人工/OCR 校验题面。
- 学业规划平台另有 10 个单科 HTML/error 响应；Xuebake 物理合集页面没有资源 ID 或直链，下载流程受登录/站点验证阻断，均保留在报告中而不冒充已导入。
- 2007 新浪条目为题号区间视觉题，答案以本地答案图保存；需后续 OCR/人工校验时才可变为逐题文本答案。
- EOL 目录共列出 94 个候选入口，其中 64 个通过年份、地区、科目一致性校验后导入；这些记录保留整页题图和可匹配的答案图，不冒充逐题 OCR。其余 30 个错链或身份不一致入口保留在抓取报告中。
- EOL 2016–2018、2020–2021 目录另有 38 个入口通过同样校验并导入；其中 2020 年答案链接无法独立校验的记录保留空答案，不把题面图冒充答案。
- EOL 2015 目录中可访问且身份一致的 5 个页面已导入；2008–2014 旧入口大多 HTTP 404，未把失效链接当作题源。
- 2023 年第三方合订 PDF 的 10 套物理卷已导入 169 道题面和 81 个整页 SVG；该文件不含答案，文字层未逐题人工核验，不能将该批次显示为“答案已核验”。
- 2023 年浙江、江苏化学 PDF 已导入 38 道题面和 29 个整页 SVG；PDF 文字层的公式/表格区域未可靠还原，已用 LaTeX 视觉来源提示 + SVG 保真兜底，不能将该批次显示为“公式已逐题转录”或“答案已核验”。
- 本轮 2018–2019 正式 PDF/视觉预览/DOCX/OLE 图形批次合计 252 道题、402 个 SVG；另有 2024 新课标理综 24 道题、19 个整页 SVG、2021 全国甲卷理综 26 道题/24 个整页或答案页 SVG，以及 2025 单科地方/区域卷 368 道题/473 个新增 PNG→SVG 侧车。2018 江苏化学的原始 DOCX 嵌入图形、2019 海南化学和 2019 天津理综教育在线原卷页、2024 新课标整卷 PDF、2021 全国甲卷物理/化学 DOCX 页、2025 单科 DOCX 嵌入图形均已转 SVG；2019 全国卷 1 物理扫描页不完整，2019 全国卷 3、2019 江苏物理、2019 海南化学、2019 天津理综、2024 新课标、2021 全国甲卷和 2025 单科 DOCX 的公式/表格仍有 LaTeX 视觉回退，书面答案与答案页保留视觉来源，均不能显示为“答案已核验”。
- 2021 全国甲卷化学第 35 题的独立来源题号为 11，公开题面 DOCX 仅提供答案页而缺少原题页；该行保留题面文字、答案页 SVG 和缺页说明，后续需人工对照完整原卷图形后才能提升核验状态。
- 2025 单科 DOCX 目录没有提供海南化学、四川化学及部分省份独立下载端点；本轮以内容去重后的区域合卷覆盖已落地端点，未把缺失端点或 GaokaoHub 乱码题卡冒充为已导入。2025 批次的文字、答案和图形均为来源摘录，`verified=0`，后续仍需逐卷人工核验。
- 2025 批次由独立审核代理只读复核：368 条题号连续、来源/别名映射一致、LaTeX 定界符与 `array` 成对、565 次 SVG 引用全部存在且已登记；复核发现的 19 条 DOCX 分页抬头泄漏（“非选择题/本部分共”等）已在导入清洗规则中截断并重跑，当前页眉模式为 0；题面中保留的“安全注意事项”属于实验小题原文，不是页眉。
- 2024 新课标整卷批次的整卷来源为 [高考直通车 PDF](https://imgs.app.gaokaozhitongche.com/resource/pdf/paper/202406/20240625072746_Ws4FOZ.pdf)，并以 [中国教育在线题页](https://gaokao.eol.cn/shiti/lz/202407/t20240702_2621046_15.shtml) 作来源交叉核对；GaokaoHub 仅用于索引，不写入其可能乱码的题干字段。
- GaokaoHub 乱码治理只对确定的运算符、分隔符、数学定界符和 HTML 表格做数据层修复；748 条含未可靠公式候选的历史卡片仍待人工对照原始页面，不能把 pending 标记当作已完成公式转录。
- 只读审核发现 10 条记录的题面与答案共用同一 SVG（其中 7 条 EOL 记录的答案页与题面页相同），64 条 EOL 记录的 `paper_name` 含 `?` 占位符；另有 83 组纸名/题号重复键，后续必须以 `source_url` 继续区分，不得静默合并。
- GaokaoHub 禁用清单的 103 条未匹配统计与 EOL 的 64 个视觉页是独立来源口径；本轮新增的全国卷/北京卷也没有替代逐省逐年清单，当前仍不能宣称“所有地方卷”已完成。
- 验收命令至少包括 `PRAGMA integrity_check`、按科目/年份/来源统计、来源 URL 非空检查、SVG 文件存在性检查和逐卷预期题号对照。
