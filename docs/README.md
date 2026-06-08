# Study AI 文档中心

本文档目录是 Study AI 的正式文档入口。文档采用“当前实现优先”的维护原则：当文档与代码不一致时，应先以代码和测试确认事实，再修正文档。

适用范围：本地开发、内网部署、受控环境运行、MCP 集成、题库与生成链路维护。

非目标：本文档不承诺未实现的外部题源、多 provider 切换、云端托管方案或未接入的 CI/CD 流程。

| 属性 | 说明 |
| --- | --- |
| 文档状态 | Maintained |
| 最近系统性重写 | 2026-05-01 |
| 权威来源 | 当前仓库代码、测试、`.env.example`、启动器 |
| 维护责任 | 改动相关功能的人同步更新相关文档 |

## 使用与入门

- `../README.md`：项目简介、启动方式、目录结构。
- `USER_GUIDE.md`：页面功能、用户工作流和使用边界。
- `TROUBLESHOOTING.md`：启动、登录、模型、任务、导出和 MCP 的常见问题。

## 开发与维护

- `DEVELOPMENT.md`：本地开发、测试、代码组织和变更规则。
- `ARCHITECTURE.md`：后端/前端/任务/crawler/生成链路的架构边界。
- `API.md`：HTTP API、认证、SSE、任务中心和主要资源接口。
- `BRANDING.md`：产品名、中文描述和内部标识的使用口径。
- `CONFIGURATION.md`：环境变量、模型供应商、搜索、导出、任务池配置。
- `QUALITY_AND_RELEASE.md`：质量门禁、验收标准和发布前检查。

## 部署与集成

- `DEPLOYMENT.md`：构建、部署、反向代理、安全检查。
- `CHERRY_STUDIO_MCP_GUIDE.md`：Cherry Studio MCP 配置和工具使用。
- `OPENAI_INTEGRATION.md`：OpenAI-compatible provider 的配置口径。

## 业务专项

- `QUESTION_SOURCE_API.md`：题源、crawler、本地题库和 provider 边界。
- `SEARCH_FILTERS_AND_BLUEPRINTS.md`：筛选项、严格学科约束和蓝图组卷。
- `STUDY_MATERIAL_IMPROVEMENTS.md`：自学资料生成质量、续流、来源清洗和改进方向。

## 历史记录

- `plans/`：历史设计和实施记录。它们只用于理解背景，不作为当前能力承诺。

## 文档维护规则

- 用户可见行为变化时，更新 `USER_GUIDE.md` 或对应专项文档。
- API、任务事件、认证或资源字段变化时，更新 `API.md`。
- 新配置项必须同时更新 `.env.example` 和 `CONFIGURATION.md`。
- 新部署依赖或外部工具链要求必须更新 `DEPLOYMENT.md`。
- 新长任务必须按 `/api/tasks` 描述；领域旧接口只写兼容说明。
- 文档不要写真实密钥、Cookie、抓取内容或本地数据库路径中的个人信息。

## 文档质量要求

正式文档应满足：

- 明确读者、范围和非目标。
- 使用可验证的路径、命令和接口名称。
- 不以计划、推测或历史行为代替当前实现。
- 对安全、数据、兼容性和失败模式给出边界。
- 修改功能时同步修改相关文档，不把文档更新留到发布后。
