# Branding

本文定义 Study AI 在产品界面、文档和集成说明中的命名口径。涉及用户可见文案时，以本文为准。

## Canonical Name

| 用途 | 名称 |
| --- | --- |
| 对外产品名 | Study AI |
| 中文描述 | 本地优先的学习与出题工作台 |
| 前端显示名 | Study AI |
| AI 助手发言名 | Study AI |

不要把“学习助手”“试卷助手”作为产品品牌继续新增。需要中文解释时，使用描述性短语，例如“学习工作台”“出题与资料生成工作流”，而不是替代品牌名。

## Internal Identifiers

以下名称属于历史或集成标识，可以保留，但不应作为用户可见品牌：

| 标识 | 保留原因 |
| --- | --- |
| `exam-paper-assistant-frontend` | `frontend/package.json` 的 npm 包名，保留以降低锁文件和脚本迁移成本。 |
| `exam-paper-assistant` | 部分 MCP/外部客户端配置中的 server key，属于机器可读标识。 |

如果未来要重命名内部标识，应作为单独迁移处理，并同步更新配置示例、文档和启动脚本。
