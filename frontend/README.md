# Study AI Frontend

本文说明 Study AI 前端应用的开发入口、目录结构、配置和质量检查要求。前端技术栈为 Vite + React + TypeScript。

## 启动

推荐从仓库根目录启动，确保后端和前端依赖由统一启动器管理：

```bash
start.bat frontend
```

或在前端目录手动启动：

```bash
cd frontend
npm install
npm run dev
```

Vite 会在终端输出访问地址，通常是 `http://localhost:5173`。

## 常用命令

```bash
npm run dev        # 本地开发
npm run lint       # ESLint
npm run build      # TypeScript 检查 + Vite 构建
npm run test       # Vitest
npm run test:watch # 监听模式
npm run e2e        # Playwright E2E
npm run preview    # 预览构建产物
```

## 目录结构

```text
src/
|-- api/          # API client 与请求封装
|-- components/   # 跨页面复用组件
|-- features/     # 按业务功能组织的组件、hooks、测试
|-- hooks/        # 共享 hooks
|-- layouts/      # 页面布局
|-- lib/          # 通用工具
|-- pages/        # 路由页面
|-- router/       # 路由配置迁移目标
|-- stores/       # Zustand 状态
|-- test/         # 测试工具
`-- types/        # 共享类型
```

新增复杂功能时优先放到 `src/features/<domain>/`，页面文件只负责装配业务视图。跨业务复用的基础组件、API 或工具再放到共享目录。

## API 基础地址

前端读取：

```bash
VITE_API_BASE_URL=/api
```

默认 `/api` 适合同源部署和本地代理。前后端分开部署时，改成后端完整地址，例如：

```bash
VITE_API_BASE_URL=https://your-backend.example/api
```

修改环境变量后需要重新运行 `npm run build`。

## 认证与任务流

- 登录页调用 `/api/auth/login`，成功后前端持久化 JWT。
- 受保护接口通过 `Authorization: Bearer <token>` 调用。
- 长任务优先使用 `/api/tasks`，前端通过 SSE 监听 `/{taskId}/stream`，并用 `after_seq` 支持断线续流。

## 质量要求

提交前按变更范围运行：

- UI 或类型变更：`npm run lint`、`npm run build`
- 组件状态或 API 行为变更：`npm run test`
- 端到端流程变更：`npm run e2e`

## 代码约定

- 使用 TypeScript strict 模式。
- 组件使用 `PascalCase`，hooks 使用 `useX`。
- 从 `frontend/src` 内部引用时优先使用 `@/` alias。
- 新的业务 UI 优先放入 feature slice，并为关键状态补充 Vitest 测试。
- 页面组件只负责路由级装配，复杂状态和副作用放入 feature hooks。

更多开发规则见 `../docs/DEVELOPMENT.md`。
