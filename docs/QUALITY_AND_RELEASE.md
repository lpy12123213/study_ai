# 质量门禁与发布检查

本文定义 Study AI 的工程质量门禁、验收标准和发布前检查。它适用于功能开发、重构、文档更新和部署准备。

## 适用范围

- 后端 API、任务运行时、生成链路、题库、crawler、MCP 工具。
- 前端页面、feature slice、API client、任务流 UI。
- 配置、部署脚本、文档和运维说明。

## 基本原则

- 可验证：完成声明必须有命令输出、测试结果或人工检查证据。
- 可回放：长任务必须可通过任务事件追踪和断线续流。
- 可恢复：失败路径应返回稳定错误信息，避免静默失败。
- 最小持久化：题目内容、密钥、Cookie 和生成物不得无意持久化或提交。
- 当前实现优先：文档不得承诺代码尚未实现的能力。

## 本地质量门禁

通用检查：

```bash
start.bat doctor
```

Linux / macOS：

```bash
./start.sh doctor
```

后端定向检查：

```bash
python -m unittest discover -s backend/tests -p "test_*.py"
python -m ruff check backend/api backend/chat backend/core backend/tests
```

前端定向检查：

```bash
cd frontend
npm run lint
npm run build
npm run test
```

文档检查：

```bash
git diff --check
```

## 变更验收标准

后端 API：

- 路由进入对应 domain router。
- 请求和响应 schema 可被 OpenAPI 展示。
- 鉴权、错误码和用户隔离行为明确。
- 新增或变更接口同步 `API.md`。

长任务：

- 通过 `/api/tasks` 提交。
- 事件包含递增 `seq`。
- 支持状态查询。
- 支持合理的失败事件。
- 前端重连使用 `after_seq`。

前端功能：

- 复杂逻辑落在 `features/<domain>`。
- 加载、空状态、错误状态和长任务状态可见。
- API client 类型与后端返回一致。
- 关键交互有测试或明确人工验证记录。

配置：

- `.env.example` 包含新增配置。
- `CONFIGURATION.md` 说明用途、默认值和安全属性。
- 密钥不出现在日志、测试快照或文档示例中。

文档：

- 文档说明当前实现，不写未落地承诺。
- 链接可解析。
- 命令和路径可在当前仓库中定位。
- 变更范围与相关文档一致。

## 发布前检查

1. 运行完整 `doctor`。
2. 检查 `git status`，确认没有误提交本地数据。
3. 检查 `.env.example` 与 `CONFIGURATION.md` 是否同步。
4. 检查 `README.md`、`USER_GUIDE.md` 和专项文档是否覆盖用户可见变化。
5. 验证登录、健康检查和至少一个长任务流程。
6. 如涉及导出，验证目标格式至少一种成功路径。
7. 如涉及 MCP，手动运行 `python -m backend.mcp.stdio_server` 并确认工具列表可加载。

## 不合格条件

以下情况不得标记为完成：

- 长任务绕过 `/api/tasks` 新增主入口。
- 新配置项没有文档和示例。
- 用户可见错误只在控制台显示，界面无反馈。
- 文档声称测试通过但未实际运行。
- 提交包含 `.env`、数据库、生成物、抓取内容、密钥或 Cookie。
