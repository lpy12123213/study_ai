# 高考真题本地导入覆盖说明

本说明记录本地题库中的高考数学真题隔离区。题目、答案与图形数据保存在被 `.gitignore` 忽略的 `.local/` 中；仓库只提交覆盖说明，不提交本地数据库、抓取缓存或生成的 SVG 文件。

## 已导入范围

- 年份：2007–2026（20 个年度）。
- 数据库出处记录：7,275 条；每条均有 `source_url`、卷名和题号。
- 2007 年补齐：21cnjy 的 39 份卷、843 个连续题号行、843 个答案字段、166 个原始预览页 SVG。
- 2007 年 SVG：原始预览页以 embedded-raster SVG 侧车保存并登记到现有 `generated_files`；题面中的公式和图形以原页视觉内容保留。
- GaokaoHub：358 个页面、5,416 个题卡、5,109 个页面答案卡；307 个无答案面板的题卡写入了显式的来源页回退标记，不伪造答案。
- 结构化数据：2010–2024 年 936 题及答案；GAOKAO-MM 80 题、142 张图像及答案，图像均有 SVG 侧车。

## 本地数据报告

- `.local/imports/gaokao-final-coverage-report.json`
- `.local/imports/gaokao-2007-source/gaokao-2007-preview-import-report.json`
- `.local/backups/exam_papers.after-gaokao-import-20260822.db`

## 可复核检查

```powershell
python -c "import sqlite3; c=sqlite3.connect('.local/exam_papers.db'); print(c.execute(\"pragma integrity_check\").fetchone()[0]); print(c.execute(\"select count(*) from gaokao_question_sources where user_id='local-user'\").fetchone()[0])"
```

当前答案/解析仍按来源标记为 `verified=0`；网页文本层缺失公式的题目以原始 SVG 页面作为完整题面依据。
