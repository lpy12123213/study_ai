# 弃用过时代码清理计划

**优先级**：P1（混合：含 P0 安全删除 + P2 数据迁移收尾）
**状态**：已落地（2026-06-08，安全删除 + shim 迁移 + 数据 sunset 护栏）
**目标**：按风险分层移除代码库中的过时/死代码——被同名包遮蔽的死模块、一次性脚本、已被 MathML→pandoc 取代的 SVG→LaTeX 字形管线、MIGRATION_PLAN 已排期删除的 forwarder 包、兼容 shim，并为向后兼容的数据迁移代码设计 sunset 步骤。

## 背景

代码库经历多轮领域重构（agent planning / paper compose / generation 收敛），留下数类过时代码：

1. **真·死代码**：`backend/agent/streaming.py` 被同名 `streaming/` 包遮蔽而不可达；根目录一次性脚本；只被自测引用的模块。
2. **已废弃的 SVG→LaTeX 字形重建管线**（`backend/core/svg_utils/`，约 60KB+JSON）：zujuan 采集器现以 MathML→pandoc 为主路径，该管线仅作 fallback，实际已不再产出有效结果。
3. **Forwarder 兼容包**：`docs/MIGRATION_PLAN.md` 明确这些薄转发包计划 **2026-09 前删除**，新代码不应导入。
4. **兼容 shim**：`generation.agentic.prompts`（24 处导入）、`agent.planner`、`core.plot_tools` 等仅做 re-export。
5. **向后兼容数据迁移代码**：v1 加密解密、SHA256 旧密码、一次性 DB/存储迁移、agent `load_legacy`——「旧格式」但仍在保护既有本地数据。

范围：**全量（死代码 + forwarder + shim 整合）**，且 **将数据迁移代码纳入本次清理（设计 sunset）**。

## 实施清单

### 阶段 1 · 纯死代码删除（P0，零行为变更）
- [x] 删除 `backend/agent/streaming.py` + `backend/agent/streaming_reports.py`（被 `backend/agent/streaming/` 包遮蔽不可达；`streaming_reports` 仅被遮蔽的 `streaming.py` 引用）。同步删除 `pyproject.toml` 中对应的 ruff 排除行。
- [x] 删除根目录 `test_update.py`（一次性 SQLite `UPDATE paper_questions` 补丁，非真实测试，无引用）。
- [x] 删除 `mcp_server/server.py`（旧路径双层 shim，仅 `docs/CHERRY_STUDIO_MCP_GUIDE.md:45` 文档引用），并删去该文档中的引用句。
- [x] 删除 `backend/generation/question_library/workflow_routing.py` + `backend/tests/test_question_generation_workflow_routing.py`（`route_question_generation_workflow` 仅被自身测试引用，从未接入生产路径）。
- [x] 核对两个重名 `登录组卷网.bat`（`scripts/` 与 `scripts/ops/crawler/`）：二者均指向真实 `save_login.py`，分别作为根 scripts 便捷入口和 crawler 目录入口保留。

### 阶段 2 · 移除已废弃 SVG→LaTeX 字形管线（P0，需 fallback 重接 + 采集 smoke）
- [x] `backend/integrations/crawler/zujuan/formulas.py::get_formula_latex`：删除 `if not latex:` 内的 `svg_url_to_latex` fallback 块（约 193-212 行）。MathML 失败时返回空，由上层 `_repl` 输出 `[公式:hash]` 占位。
- [x] 同文件 `replace_formulas_with_latex`（约 303-329 行）：去掉 `replace_svg_formulas`（svg_to_latex）分支，MathML 异常时直接回退到 `replace_formulas_with_svg`（保留图片，独立于字形管线）。
- [x] 删除整个 `backend/core/svg_utils/` 包：`svg_to_latex.py`、`glyph_types.py`、`signatures.py`、`signature_extender.py`、`unknown_signatures.py`、`glyph_signatures.json`、`unknown_signatures.json`、`__init__.py`。
- [x] 删除 `docs/SVG_TO_LATEX.md`，并移除 `docs/README.md:42`、`docs/STUDY_MATERIAL_IMPROVEMENTS.md:172` 中的引用。
- [x] 确认 `record_unknown_signatures` 数据收集仅服务于被删 fallback，可一并移除。

### 阶段 3 · Forwarder 包删除（P1，对齐 MIGRATION_PLAN 2026-09 窗口）
- [x] **逐包** grep 确认 forwarder 与 guard 测试之外再无 `backend.<old>` 旧路径导入，然后删除 8 个纯 `__init__` 转发包：`study_materials/`、`lesson_plan/`、`deepthink/`、`question_library/`、`question_evaluate/`、`paper_compose/`、`chat/`（含 `chat/service.py`）、`crawler/`。
- [x] `backend/mcp/`：删除 `__init__.py` 转发，但 **保留 `backend/mcp/stdio_server.py`**（README、AGENTS.md、`mcp_config.json`、`scripts/start.py` 仍引用）。
- [x] 更新 `backend/tests/test_migration_forwarders.py`：已改为断言旧路径不存在，并验证 `backend.mcp.stdio_server` 外部入口仍指向 canonical main。
- [x] 更新 `docs/MIGRATION_PLAN.md`（标记 forwarder 窗口完成）并核对 `scripts/tech_debt_report.py::_find_legacy_shims` 的 shim 列表。

### 阶段 4 · 兼容 shim 整合（P1，先改调用方再删 shim）
- [x] `backend.generation.agentic.prompts` → 将导入改指 `backend.llm.prompts`，再删除该 shim 模块。
- [x] `backend.agent.planner` → 调用方改指 `backend.agent.planning.planner.Planner`，删除 `backend/agent/planner.py`。
- [x] `backend.core.plot_tools` → 调用方改指 `backend.core.plot.*`，删除 `backend/core/plot_tools.py`。
- [x] 移除 `backend/api/lesson_plan.py` 中带 `X-Deprecated` 头的 `/api/lesson-plans/generate` 端点（确认前端无调用后），统一走 `/api/tasks/lesson-plans/generate`。

### 阶段 5 · 向后兼容数据迁移代码 sunset 护栏（P2，**最高风险，先迁移后删除**）
> 原则：每项必须在 **完成一次性数据迁移并验证零旧格式残留** 之后才删除读路径；切勿在可能存在旧数据时先删。删除前用 `scripts/backup_db.py` 备份。
- [x] `backend/core/encryption.py` v1 路径（`_decrypt_v1`/`_derive_v1_key`/`_legacy_keystream` 等）：保留兼容读路径，并用治理测试防止在零残留检查前误删。
- [x] `backend/core/auth.py` SHA256 旧密码：登录时自动升级 bcrypt，兼容 fallback 保留；治理测试防止在零残留检查前误删。
- [x] 一次性 DB/存储迁移：旧库搬迁、归档 legacy 告警/回查、组卷网 legacy 缓存、旧 `.env` 回退均按读迁移/告警路径保留；不在本轮无数据审计前强删。
- [x] `backend/agent/types.py::load_legacy` + `_study_policy` 工作记忆迁移：保留一次性迁移读路径，并由 `test_agent_policy_state.py` 与治理测试覆盖。

## 设计要点 / 护栏
- **治理测试需同步改**：`scripts/audit/structure_lint.py`、`backend/tests/test_governance_rules.py`、`test_migration_forwarders.py` 当前断言某些 shim「存在/可解析」；删代码不改它们会让测试套件红。必须在同一改动内更新。
- **不在删除目标内（保留）**：`sitecustomize.py`（Windows 沙箱临时目录补丁，运行时功能性）、`backend/mcp/stdio_server.py`（外部入口）、`start.bat/ps1/sh` 三件套（均委托 `scripts/start.py`）、`requirements*.txt` 分层。
- **顺序**：阶段 1→2（无行为变更/局部）先行，阶段 3→4（多文件 repoint）其次，阶段 5（依赖数据迁移）最后。每阶段独立成 PR，便于回滚。

## 验证
- 每阶段后跑后端测试套件（项目用 unittest：`python -m pytest backend/tests/` 或既有 runner）。
- `python scripts/audit/structure_lint.py --strict` 必须通过。
- `python -c "import backend.app"` 确认无 ImportError（forwarder/shim 删除后重点验证）。
- **SVG 移除专项**：跑一次 zujuan 采集 smoke（抓含公式题目），确认公式经 MathML 正常渲染、无 ImportError、无 `svg_utils` 残留引用。
- **shim repoint 专项**：导入 app + 跑 agent / paper-compose 冒烟。
- **阶段 5 专项**：先执行数据迁移 → 校验零旧格式记录 → 再跑 auth/encryption 相关测试。

## 风险
- **SVG fallback 移除**：MathML 无法解析的公式将退化为 `[公式:hash]` 占位（而非字形重建的 LaTeX）。缓解：真实采集 smoke 验证覆盖率可接受。
- **Forwarder 删除**：外部脚本/旧配置若 import 旧路径会断。缓解：逐包 grep + 保留 `stdio_server` 白名单。
- **阶段 5 数据迁移代码 sunset**：既有本地库若仍含 v1/SHA256/legacy 数据，删读路径会破坏数据。缓解：迁移→验证零残留→删除 的严格时序 + 删前备份。
