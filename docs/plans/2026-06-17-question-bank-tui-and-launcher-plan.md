# 本地题库维护 TUI 工具 + 统一启动箱 - 实施方案

**优先级**: P2, 工具/CLI(本地题库长期维护)
**状态**: 已实现(2026-06-08)
**目标**: 为本地题库的长期维护工作(浏览 / 审核策展 / 质量校验 / 去重统计)提供 4 个独立可单跑的 TUI 小工具;并新增一个统一的 TUI 启动箱,集中统管题库工具 + 出题/爬取 + 后端/前端/MCP 服务(服务复用 `scripts/start.py`)。

技术栈沿用既有约定:`argparse + rich + prompt_toolkit`(无 typer/click/textual),rich/prompt_toolkit **惰性导入 + 无依赖时优雅降级**。参考实现:`backend/cli/question_generate/` 包。

## 实施清单

- [x] 新增 `backend/cli/common.py`:复制 question_generate 的稳定轻量 helper(console / availability / prompts / `_safe_user_id`),供新工具共享(不改动 question_generate)
- [x] 新增 `backend/cli/question_bank/_ui.py`:题库条目表格渲染 + 详情面板(纯文本兜底)
- [x] browse 工具(只读):`list_question_library_items` 分页 / 筛选 / 详情
- [x] review 工具(写):`list_unscored_question_ids` 待审队列 + 逐题 star/hide/评分
- [x] validate 工具(默认只读,`--fix` 选择性写):缺答案/缺解析、低 `quality_score`、`quality_flags`、疑似坏 LaTeX/残留占位符
- [x] stats 工具(只读):学科/来源/分数/思维方法聚合 + `stem_fingerprint` 去重
- [x] 新增 `backend/cli/launcher/`:分组交互菜单 + 前台子进程派发
- [x] 修改 `scripts/start.py`:新增 `menu`/`launch`/`tui` 子命令 + help 一行(使 `start.bat menu` 可用)
- [x] 新增测试:`test_question_bank_validate.py`、`test_question_bank_dedup.py`、`test_launcher_dispatch.py`
- [x] 端到端验证:冒烟 / 播种 / 功能 / 无 rich 降级 / 回归测试

---

## 问题描述

本地题库(`QuestionLibraryItem` 按 user 维度 + 全局 `QuestionCache` 存题面/答案/解析)已积累爬取题与 AI 题,但**长期维护工作**没有趁手工具:待审爬取题靠零散处理、低质量题(缺答案/解析、坏公式)无批量发现手段、重复题无检视入口、题库分布无统计视角。同时启动入口分散(`python -m backend.cli.xxx`、`scripts/start.py`),缺一个统一菜单。

用户已确认的方向:
1. 题库工具做成**多个独立小工具**(各自 `python -m`),而非单一仪表盘。
2. 启动箱做成 **TUI 菜单,统管工具 + 服务**(服务复用 `scripts/start.py`)。

## 关键事实(已读源码核实)

- **user_id 约定**:CLI 统一 `--user-id`,缺省经 `_safe_user_id` 归一为 `"1"`(`backend/cli/question_generate/helpers.py:107-109`);仓储 `_require_user_id` 强制非空(`question_library.py:19-23`)。无 env / 专用本地用户常量。
- **`list_question_library_items` 回传字段**(`question_library.py:218-242`)含 `stem / question_type / knowledge_point / quality_score / has_answer / has_analysis`,**但不含** `stem_fingerprint / quality_flags / answer 正文 / analysis 正文` —— 后者在 `QuestionCache`,用 `get_question_cache(question_ids=[...])` 批量补齐(`backend/database/repositories/question/question_cache.py:52-90`)。**无需新增仓储函数。**
- **待审队列**:`list_unscored_question_ids(user_id, subject, limit)` = `origin=="crawled" AND ai_score IS NULL`(`question_library.py:388-413`)。
- **策展写入**:`set_hidden` / `set_starred`(`question_library.py:277-342`)、`upsert_question_library_items`(只写出现的键,`:44-103`);`session=None` 时自管事务并提交。
- **思维方法统计**:`list_thinking_method_stats`(`question_library.py:416`,已按 count 降序)。
- **全文检索**:`search_fulltext`(`backend/database/repositories/system/search.py:43`)**只覆盖 conversation/paper/study_archive 的 FTS,不含 question_library** —— 故近似去重只能作为"该题面也出现在某份已存试卷里"的提示。
- **`scripts/start.py` 分发**:`main()` 在 `:303-363` 按 `cmd` 分支;`ROOT`、`ensure_venv(ROOT)`、`_run_checked([str(vpy),"-m",...], cwd=ROOT)` 均可复用。`start.bat`/`.ps1`/`.sh` 透传参数,故加子命令后 `start.bat menu` 自动可用。

## 文件布局(全部在 `backend/cli/` 下,业务逻辑禁止进 `scripts/`)

```
backend/cli/
  common.py                       # 新增:共享 UI 原语
  launcher/
    __init__.py  __main__.py  app.py
  question_bank/
    __init__.py
    _ui.py                        # 新增:题库条目表格 + 详情面板渲染
    browse/   __init__.py __main__.py app.py
    review/   __init__.py __main__.py app.py
    validate/ __init__.py __main__.py app.py
    stats/    __init__.py __main__.py app.py
```

`python -m` 入口:`backend.cli.question_bank.{browse,review,validate,stats}` 与 `backend.cli.launcher`。每个 `__main__.py` = `from .app import main` + `if __name__=="__main__": main()`(仿 `question_generate/__main__.py`);每个 `app.py` 暴露 `def main(argv=None)`,argparse 解析后对异步 DB 调用用 `asyncio.run(...)`(仿 `question_generate/app.py:20-51`)。

### `backend/cli/common.py`(新增,仅供新工具使用)

从 `question_generate/helpers.py`、`prompts.py` **复制**这些**轻依赖**原语(不 import 其私有名、不改 question_generate,避免牵动已工作代码 / 不引入 `preview_store` 重导入链):
- `_rich_available` / `_prompt_toolkit_available` / `_console`(含 `_PlainConsole` 兜底)/ `_safe_user_id`
- `_prompt_text`(**保留 `prompts.py:36-51` 的"运行中事件循环→回退 input()"守卫**)、`_prompt_choice`、`_prompt_bool`、`_prompt_int`
- logger 命名沿用 `get_logger("backend.cli.<tool>")`

> 这是 ~40 行稳定小函数的二次落地(question_generate 与 common 各一份,共 2 份,符合"三次才抽象");4 个题库工具共享同一份 common。后续如需统一可再把 question_generate 切到 common,本期不动。

### `backend/cli/question_bank/_ui.py`(新增)

- `render_items_table(console, items)`:rich `Table`(列:序号/qid/学科/类型/分数/★/隐/has_ans/has_ana);无 rich 时编号列表打印。
- `render_item_detail(console, item, cache_row)`:rich `Panel`+`Markdown`(仿 `question_generate/render.py:_render_question_panel:109-134`),展示题面/答案/解析/ai_verdict;纯文本兜底。

## 4 个题库工具设计(均 `--user-id` 默认 `"1"`;异步 DB 调用走 `asyncio.run`)

### 1. browse 浏览/检索/筛选(只读) `question_bank/browse/app.py`
参数:`--subject --origin --hidden(0|1|all,默认0) --q --min-score --sort(updated_at|ai_score) --order --limit(默认20) --page`。
调 `list_question_library_items(..., include_total=True)`(`question_library.py:106`)分页。键盘循环(经 `_prompt_text`):`n/p` 翻页、`s` 改检索、`f` 切隐藏过滤、输入序号→详情面板(用 `get_question_cache([qid])` 补答案/解析)、`q` 退出。**无写入。**

### 2. review 审核策展(写) `question_bank/review/app.py`
参数:`--subject --limit(默认50)`。队列取 `list_unscored_question_ids`(`question_library.py:388`),批量 `get_question_cache` 补题面。逐题渲染 `Panel` + 键盘循环:
- `s` 收藏 → `set_starred(user_id, question_id, starred=True)`(`:311`)
- `h` 隐藏 → `set_hidden(user_id, question_id, hidden=True)`(`:277`)
- `1..5` 评分 → `upsert_question_library_items(user_id, items=[{question_id, ai_score, ai_verdict}])`(`:44`,只写出现键 `:87-93`)
- `n` 跳过、`b` 上一题、`q` 退出。每动作一次短 `asyncio.run`,仓储自管提交。

### 3. validate 质量校验(默认只读,`--fix` 选择性写) `question_bank/validate/app.py`
参数:`--subject --limit(默认200) --min-quality --fix(默认关) --fix-action(hide|flag)`。
翻页 `list_question_library_items(hidden="all")` 收集 qid → 批量 `get_question_cache` 补 `stem_fingerprint/quality_flags/answer/analysis`。**纯规则判定(无 LLM)**:缺答案(`has_answer` 假)、缺解析(`has_analysis` 假)、`quality_score < --min-quality`、`quality_flags` 非空、题面正则命中疑似 LaTeX 损坏 / 残留占位符(`\(...\)`、`\[...\]`、`[公式:hash]`、`[图片:url]`)。输出 rich 发现清单 `Table` + 汇总;长扫描可挂 `live_ui` 进度(`live_ui.py:69`)。`--fix`(经 `_prompt_bool` 二次确认)→ `set_hidden(...)` 或 `upsert_question_library_items(ai_verdict="needs_fix")`。**默认运行绝不改库。**

### 4. stats 统计与去重(只读) `question_bank/stats/app.py`
参数:`--subject --limit --dedup --query`。聚合:按 学科/来源/分数桶/隐藏/收藏 计数(来自 `list_question_library_items(hidden="all")`);思维方法家族用 `list_thinking_method_stats`(`question_library.py:416`)。`--dedup`:enrich 后按 `stem_fingerprint` 分组,簇 >1 即重复(**库内去重主路径**)。近似重复信号用 `search_fulltext(types=["paper"])`(`search.py:43`)——**注意其 FTS 不含 question_library**,输出须写清"也出现在已存试卷"这一区别。本期不做删除(`bulk_delete_question_library_items` 暂不接)。

## 启动箱设计 `backend/cli/launcher/app.py`

`main(argv=None)`:构造 `_console()`,先用 `_prompt_text` 问一次 `--user-id`(默认 `"1"`)转发给题库/出题工具,然后循环渲染分组菜单(rich `Panel`/`Table`,纯文本兜底):
- **题库工具**:1 浏览 / 2 审核 / 3 校验 / 4 统计去重
- **出题与爬取**:5 `backend.cli.question_generate` / 6 `backend.cli.question_library_crawl`
- **服务(复用 start.py)**:7 backend / 8 frontend / 9 mcp / 10 dev / 11 all
- **0 退出**

**派发机制:一律前台子进程**,子进程结束后重绘菜单:
- 工具:`subprocess.call([sys.executable, "-m", "backend.cli.question_bank.browse", "--user-id", uid], cwd=ROOT)`
- 服务:`subprocess.call([sys.executable, str(ROOT/"scripts"/"start.py"), "backend"], cwd=ROOT)`

`ROOT = Path(__file__).resolve().parents[3]`(launcher→cli→backend→repo 根)。**不用 `shell=True`**、传 argv 列表 → 规避中文路径 `C:\Users\李\...` 的引号问题;`sys.executable` 在 Windows 正确(`.cmd` 问题只影响 npm)。子进程内 `KeyboardInterrupt` 捕获后回菜单;菜单态 Ctrl+C 退出。

**为何全部子进程(而非 in-process 调 `main()`)**:启动箱自身持有 prompt_toolkit,题库/出题工具及 `question_generate` 的 review 循环也驱动 prompt_toolkit——同进程两个实例会损坏 TTY 并触发"`asyncio.run` 在运行中的 loop 里"崩溃(代码已有守卫 `prompts.py:36-51`);子进程获得干净 stdin/stdout 且崩溃隔离。服务本就是长驻进程,必须子进程。

### `scripts/start.py` 集成
在 `main()`(`:303-363`)未知命令兜底前插入(保持 scripts/ 无业务逻辑——只转发):
```python
if cmd in {"menu", "launch", "tui"}:
    vpy = ensure_venv(ROOT)
    _run_checked([str(vpy), "-m", "backend.cli.launcher"], cwd=ROOT)
    return 0
```
并在 help 文本(`:312-325`)加一行 `start.bat menu  (打开 TUI 启动箱)`。包装脚本已透传参数,无需改动。

## 验证(Windows / bash)

DB 路径由 `backend/database/paths.py:resolve_db_path()` 决定(`.local/exam_papers.db`,或 `STUDY_AI_DB_PATH`)。
1. **冒烟**:`python -m backend.cli.question_bank.browse --help`(review/validate/stats 同);`python -m backend.cli.launcher`(菜单渲染、`0` 退出);`python scripts/start.py menu` 与 `start.bat menu`。
2. **播种**:`STUDY_AI_DB_PATH=.local/test_tui.db python -m backend.cli.question_library_crawl --user-id 1 --subject 高中物理 --target 5`,然后查 `question_library` / `question_cache` 表。
3. **功能**:browse 翻页;review 对一题 star/hide/评分,再跑 browse 确认已持久化;validate `--min-quality 60`(确认不改库),再 `--fix` 走一遍确认确认对话;stats `--dedup`。
4. **降级**:在无 rich/prompt_toolkit 环境(或临时令 `_rich_available()` 返回 False)跑一遍,确认纯 `print`/`input` 路径可用。
5. **回归**:`python -m unittest discover -s backend/tests -p test_*.py`(与 doctor 同闸 `start.py:197-198`)。
6. **新增轻量测试**(风格仿 `backend/tests/test_question_library_repository.py`:`IsolatedAsyncioTestCase` + 临时 sqlite + `patch.object(repo, "async_session_maker", session_maker)`;工具 `main(argv)` 可注入参数、无需 TTY):
   - `test_question_bank_validate.py`——LaTeX/占位符检测 + 分类纯函数。
   - `test_question_bank_dedup.py`——两条共享同一 `stem_fingerprint` 的 cache 行 → 1 个大小为 2 的重复簇。
   - `test_launcher_dispatch.py`——`patch("subprocess.call")` 后断言各菜单项构造的 argv 正确。

## 风险 / 边界

- **空题库 / 无该用户数据**:`list_*` 返回空,渲染"题库为空"并干净退出;review 空队列提示"没有待复核的题目"。
- **无 rich**:渲染经 `_rich_available()` 门控,`_console()`→`_PlainConsole`,live→`_NullLive`(`live_ui.py:32`)。
- **async-loop-in-prompt**:prompt 放在 `asyncio.run(...)` 之外(同步键盘循环 + 每动作一次短 `asyncio.run`);子进程启动箱杜绝嵌套 loop 损坏。
- **`get_question_cache` 缺行**:库条目对应 cache 行被删时该 qid 被省略(`question_cache.py:69-90`),按"题面不可用"处理,绝不 KeyError。
- **FTS 不可用**:`search_fulltext` 回退 LIKE / 返回 `[]`;去重以 `stem_fingerprint` 为主路径。
- **Windows 终端**:依赖 `start.bat` 的 `chcp 65001`;rich 走 utf-8;子进程 argv 列表 + `cwd=ROOT` 规避中文路径引号问题。

## 关键修改/新增文件

- 新增:`backend/cli/common.py`、`backend/cli/question_bank/`(`_ui.py` + `browse/review/validate/stats` 四子包)、`backend/cli/launcher/`
- 修改:`scripts/start.py`(新增 `menu` 子命令 + help 一行)
- 新增测试:`backend/tests/test_question_bank_validate.py`、`test_question_bank_dedup.py`、`test_launcher_dispatch.py`
- 复用(不改):`question_library.py`、`question_cache.py`、`system/search.py`、`question_generate/{helpers,prompts,render,live_ui}.py`
