# 前端架构与基础框架设计提案

> 状态：Proposed
>
> 日期：2026-07-25
>
> 适用范围：当前 clean-room `frontend/` 与现行 FastAPI 契约
>
> 性质：架构设计记录，不代表功能已实现或迁移已完成

> 视觉与交互伴随规范：[前端视觉系统与工具对话体验规划](./2026-07-25-frontend-visual-conversation-design.md)

## 1. 摘要

Study AI 当前最适合的前端基础形态不是迁移到 Next.js、TanStack Start、Astro 或通用管理后台框架，而是继续采用：

- Vite + React + TypeScript。
- React Router Data Mode。
- TanStack Query 管理 HTTP 服务端状态。
- Zustand 管理少量全局客户端 UI 状态。
- Tailwind CSS + Radix UI 作为设计系统基础。
- 独立的 Task/Stream Coordinator 管理 SSE、任务状态机、断线重连和事件投影。

目标架构是一个 **client-first、feature-sliced 的领域模块化单体**。

当前主要瓶颈不是框架能力不足，而是：

1. 路由页面已经承担过多业务职责。
2. HTTP、认证、全局 UI 和业务提示之间存在反向依赖。
3. SSE 只统一了传输格式，没有统一不同领域的事件语义。
4. REST、URL、任务流和本地 UI 状态的所有权尚未明确。
5. 当前没有前端自动化测试基础设施。
6. 所有业务页面同步进入一个主 JavaScript 包。

本提案要求在保留现有 URL、操作流、FastAPI 同源部署和 clean-room 边界的前提下，分阶段完成架构收敛，不进行一次性重写。

## 2. 设计来源与边界

本提案只依据以下当前材料：

- 当前磁盘上的 clean-room `frontend/`。
- 当前 `backend/api/**`、任务运行时、认证和静态托管契约。
- 当前非历史主文档，如 `docs/ARCHITECTURE.md`、`docs/API.md` 和 `docs/DEPLOYMENT.md`。
- 各候选框架截至 2026-07-25 的官方文档。

严格遵守 `FRONTEND_CLEAN_ROOM_REWRITE.md`：

- 不读取或恢复已删除前端的 Git 历史、blob、diff、缓存或构建产物。
- 不以已删除前端的布局、组件层级、导航或交互流为参考。
- 当前已经实现的 clean-room 操作流视为迁移期间需要保护的基线。

## 3. 当前架构快照

### 3.1 技术栈

当前前端声明的主要依赖：

- React 18.3。
- React Router 7。
- TanStack Query 5。
- Zustand 5。
- Vite 6。
- TypeScript strict。
- Tailwind CSS 4。
- Radix UI primitives。
- react-markdown、KaTeX 和相关 Markdown 插件。

当前路由通过 `createBrowserRouter` 创建，已经属于 React Router Data Mode，但尚未使用其主要架构能力：

- route lazy。
- route loader/action。
- route error boundary。
- route handle/metadata。
- 统一 pending UI。
- URL 搜索参数作为页面状态。

### 3.2 部署模型

当前部署主路径是：

```text
Browser
  ├─ HTTP / SSE / download
  v
FastAPI
  ├─ /api/*
  ├─ /assets/*
  └─ index.html SPA fallback
```

FastAPI：

- 托管 `frontend/dist/assets`。
- 对非 `/api` 的 GET/HEAD 请求回退 `frontend/dist/index.html`。
- 使用同源 Cookie 和可选 Bearer Token。
- 同时承载 REST、SSE、WebSocket、媒体代理和生成文件下载。

这一模型已经满足本地优先和内网部署需求。增加第二个 Node.js 运行时只会扩大 Cookie 转发、流式响应、取消传播、下载代理和运维复杂度。

### 3.3 代码规模

2026-07-25 的静态统计：

| 指标 | 当前值 |
| --- | ---: |
| 页面文件 | 14 |
| 页面代码总行数 | 9,189 |
| 超过 600 行的页面 | 8 |
| 超过 1,000 行的页面 | 2 |
| `library.tsx` | 1,716 行 |
| `compose.tsx` | 1,468 行 |
| 当前业务 JS 主包 | 1,167,318 bytes |
| 当前业务 JS 主包 gzip | 约 352.83 kB |

页面文件同时承担：

- API 查询和 mutation。
- query key 定义与缓存失效。
- SSE 连接、AbortController 和事件 switch。
- 任务投影。
- 表单和筛选状态。
- 完整业务 UI。

这与 `docs/ARCHITECTURE.md` 中“feature slice + 页面只做路由装配”的目标存在明显差距。

### 3.4 当前依赖问题

#### HTTP 与状态层循环依赖

当前依赖方向包括：

```text
stores/auth.ts
  -> lib/api/client.ts
  -> stores/auth.ts
```

同时，HTTP client 直接调用 UI store 展示 toast 和组卷网提示。这使基础传输层：

- 依赖 React/Zustand 运行时。
- 难以隔离测试。
- 难以用于 route loader、脚本或其他运行环境。
- 难以替换认证策略。

#### 路由信息有多份真源

当前路由信息分别存在于：

- `src/router.tsx`：真实路由。
- `src/components/layout/sidebar.tsx`：导航。
- `src/components/layout/topbar.tsx`：标题正则。

新增或修改路由需要同步多处，并且容易出现标题、导航、权限和实际路由不一致。

#### Query 约定散落

query key 和 query function 直接写在页面组件里。缺少：

- 领域 query key factory。
- `queryOptions`。
- loader 预取复用。
- 统一 mutation invalidation。
- 领域级错误映射。

#### API 类型仍以手写为主

当前 FastAPI `/api` OpenAPI 导出快照包含：

- 185 个 operation。
- 81 个 component schema。

但后端代码仍有约 94 处 `response_model=dict`、`Dict[str, Any]` 或类似泛化响应，因此自动生成类型目前只能作为契约基线，不能代替领域适配和运行时校验。

#### 缺少测试基础

当前 `package.json` 没有 `test` 或 `test:e2e` 脚本，也没有现存 test/spec 文件。以下关键行为没有自动化保护：

- SSE 分帧。
- `after_seq` 续播。
- 非终态 error。
- EOF 后状态校准。
- `pending_review`。
- pause/resume/retry/cancel。
- Snapshot 与 delta 的不同语义。
- 路由深链和筛选状态恢复。

## 4. 决策目标

### 4.1 目标

- 保持单一 FastAPI 运行时和同源 SPA 部署。
- 保持现有 URL 与用户操作流。
- 页面只负责 URL、loader 和 feature 装配。
- 业务能力按领域垂直切分。
- 明确每类状态的唯一所有者。
- 让流式任务具有显式、可测试、可恢复的状态机。
- 让 HTTP client 成为纯基础设施。
- 让 API 契约漂移能在构建或测试阶段暴露。
- 实现按路由代码分割。
- 为后续 React/React Router 大版本升级建立稳定边界。

### 4.2 非目标

- 不恢复或参考已删除前端。
- 不在本轮改变视觉设计语言。
- 不改变现有路由信息架构。
- 不迁移到 SSR。
- 不引入第二个 BFF。
- 不把 FastAPI 业务逻辑搬到 TypeScript。
- 不一次性重写所有页面。
- 不在架构迁移中顺便改变后端任务运行模型。

## 5. 基础框架决策

### 5.1 采用：Vite + React Router Data Mode

React Router Data Mode 是当前最佳选择。

原因：

- 当前已经使用 `createBrowserRouter`，迁移成本最低。
- 原生支持 lazy route、loader、action、error boundary 和 route handle。
- 可以继续输出普通静态资源，由 FastAPI 托管。
- 不要求额外 Node.js 服务。
- 与 TanStack Query 和浏览器直连 SSE 没有冲突。
- 允许逐个路由迁移，不需要一次切换全部页面。

官方资料：

- [React Router 模式说明](https://reactrouter.com/start/modes)
- [Data Mode Route Object](https://reactrouter.com/start/data/route-object)
- [Route lazy](https://reactrouter.com/start/data/route-object#lazy)

### 5.2 保留候选：React Router Framework SPA Mode

Framework Mode 的主要收益：

- route module 约定。
- 路由类型生成。
- 自动代码分割。
- 更完整的 pending/error/metadata 模型。
- 为以后预渲染或 SSR 保留迁移路径。

当前暂不采用，原因：

- `ssr: false` 仍会在构建期渲染根路由。
- 根路由仍必须 SSR-safe。
- 需要引入 `@react-router/dev`、`@react-router/node` 和新的构建约定。
- 当前主要问题是业务边界和流式状态，不是路由类型生成。
- 会把入口迁移、Provider 迁移、路由迁移和业务拆分耦合在一起。

官方资料：

- [React Router SPA Mode](https://reactrouter.com/how-to/spa)
- [React Router Pre-Rendering](https://reactrouter.com/how-to/pre-rendering)

### 5.3 保留候选：TanStack Router

TanStack Router 的优势：

- params、navigation 和 search params 具有较强的类型推导。
- 搜索参数支持 schema 校验。
- 文件路由和自动代码分割成熟。
- 与 TanStack Query 的协调方式明确。

当前暂不迁移，原因：

- 当前路由数量不多。
- React Router 本身不是已证实的性能或维护瓶颈。
- 迁移需要替换 Link、navigate、params、Outlet 和 RouterProvider 等现有表面。
- 它不能自动解决 HTTP 循环依赖、SSE 语义冲突和巨型页面。

当以下条件同时出现时重新评估：

- 筛选/分页/工作区状态大量进入 URL。
- 搜索参数类型错误成为高频缺陷。
- route catalog 和 Data Mode 仍不能满足维护需求。

官方资料：

- [TanStack Router Search Params](https://tanstack.com/router/latest/docs/guide/search-params)
- [TanStack Router Code Splitting](https://tanstack.com/router/latest/docs/guide/code-splitting)

### 5.4 不采用：Next.js

不采用原因：

- 完整能力需要第二个 Node.js 运行时。
- 浏览器到 FastAPI 之间会增加额外 BFF 或代理层。
- SSE、Cookie、文件下载和取消传播会变复杂。
- 当前大部分页面仍会是 Client Components。
- 静态导出模式不支持动态 Cookie、rewrites、Server Actions 等核心运行时能力。
- 当前没有足够的 SEO 或公开内容渲染收益。

官方资料：

- [Next.js SPA](https://nextjs.org/docs/app/guides/single-page-applications)
- [Next.js Static Exports](https://nextjs.org/docs/app/guides/static-exports)

### 5.5 不采用：TanStack Start

不采用原因：

- 截至当前官方仍标记为 Release Candidate。
- 主要价值是 full-document SSR、server functions、API routes 和全栈构建。
- 这些能力与现有 FastAPI 职责重叠。
- 会引入第二个服务端运行时和新的部署边界。

官方资料：

- [TanStack Start Overview](https://tanstack.com/start/latest/docs/framework/react/overview)

### 5.6 不采用：Astro

Astro 主要面向内容驱动网站。Study AI 是持续交互、长任务、SSE、工作区和大量客户端状态组成的应用。如果采用 Astro，主要业务最终会成为一个大型 React island，无法获得 islands 架构的主要收益。

官方资料：

- [Why Astro](https://docs.astro.build/en/concepts/why-astro/)

### 5.7 不采用：通用 CRUD 管理后台框架

不建议使用 Refine、React Admin、Ant Design Pro 等作为应用底座。

原因：

- Study AI 的核心界面是对话、生成、人工审核、流式进度、试卷工作区和内容预览。
- 这些交互不是典型 CRUD。
- 管理后台框架会带来额外数据提供器、布局和组件约束。
- 当前 Tailwind + Radix 已经提供足够的设计系统基础。

## 6. 目标架构

### 6.1 总体结构

```text
src/
├─ app/
│  ├─ providers/
│  │  ├─ query-provider.tsx
│  │  ├─ theme-provider.tsx
│  │  └─ error-reporter.ts
│  ├─ router/
│  │  ├─ router.tsx
│  │  ├─ route-catalog.ts
│  │  └─ route-error-boundary.tsx
│  └─ shell/
├─ routes/
│  ├─ home.route.tsx
│  ├─ chat.route.tsx
│  ├─ compose.route.tsx
│  └─ ...
├─ features/
│  ├─ chat/
│  ├─ paper-compose/
│  ├─ paper-library/
│  ├─ question-library/
│  ├─ study-materials/
│  ├─ deepthink/
│  ├─ task-center/
│  ├─ settings/
│  └─ sharing/
├─ entities/
│  ├─ task/
│  ├─ paper/
│  ├─ question/
│  ├─ conversation/
│  └─ study-archive/
└─ shared/
   ├─ api/
   ├─ streaming/
   ├─ auth/
   ├─ ui/
   └─ lib/
```

### 6.2 依赖方向

只允许以下方向：

```text
app -> routes -> features -> entities -> shared
```

规则：

- `shared` 不得导入 `entities`、`features`、`routes` 或 `app`。
- `entities` 不得导入 `features`。
- feature 之间不得直接导入内部文件。
- 跨 feature 协作通过 entity contract、shared event 或 app orchestration。
- route 不实现领域算法。
- UI primitive 不读取业务 store。
- HTTP client 不导入 React、Zustand 或具体业务模块。

### 6.3 Feature 标准结构

复杂 feature 采用：

```text
features/<feature>/
├─ api/
│  ├─ client.ts
│  ├─ queries.ts
│  └─ mutations.ts
├─ model/
│  ├─ types.ts
│  ├─ reducer.ts
│  └─ selectors.ts
├─ streaming/
│  ├─ contract.ts
│  ├─ decode-event.ts
│  └─ project-event.ts
├─ ui/
├─ route.tsx
└─ __tests__/
```

简单 feature 可以省略不需要的目录，不为了形式制造层级。

## 7. 状态所有权

每一份状态必须有唯一所有者。

| 状态类型 | 所有者 | 示例 |
| --- | --- | --- |
| 可分享、可恢复的页面状态 | URL | tab、page、filter、sort、selectedId |
| REST 服务端状态 | TanStack Query | papers、tasks、archives、settings |
| 长任务实时投影 | Task/Stream Coordinator | lastSeq、connection、live progress |
| 持久任务真源 | FastAPI / database | status、result、events |
| 全局客户端 UI | Zustand | theme、sidebar、search dialog、toast |
| 局部交互状态 | React local state | dialog open、临时输入、hover |
| 复杂表单状态 | feature form model | compose blueprint、generation config |
| 可恢复草稿 | feature storage adapter | chat draft、compose draft |

禁止：

- 把 REST 响应复制进 Zustand。
- 把筛选和分页只放在页面 `useState`。
- 把任务连接对象放进 TanStack Query cache。
- 让多个页面各自解释同一种任务事件。

## 8. 路由设计

### 8.1 单一 Route Catalog

建立唯一 route catalog，至少包含：

```ts
interface AppRouteMeta {
  id: string;
  path: string;
  title: string;
  nav?: {
    group: string;
    label: string;
    icon: string;
    order: number;
  };
  public?: boolean;
  layout: "shell" | "public";
}
```

由它派生：

- 路由对象。
- 侧栏导航。
- 顶栏标题。
- 面包屑。
- 命令面板入口。
- 权限和公开页标记。

不再维护 pathname 正则标题表。

### 8.2 Route Module 职责

route module 只负责：

- 解析 path params 和 search params。
- 执行必要的 loader/prefetch。
- 选择 layout。
- 定义 route-level error boundary。
- 装配 feature 页面。

复杂查询、mutation、事件解释和 UI 不进入 route 文件。

### 8.3 Lazy Route

除 app shell 和最小启动页外，所有业务路由通过 `lazy` 加载。

目标：

- 主入口不再同步导入所有页面。
- Markdown、KaTeX、复杂工作区和低频设置不进入初始 shell chunk。
- Vite 输出多个可缓存的领域 chunk。

### 8.4 URL 状态

以下状态应进入 URL：

- Library：搜索词、学科、难度、类型、分页、tab。
- Compose：tab、review task ID。
- Tasks：status、task type、selected task。
- Papers：keyword、page。
- Materials：archive/task ID。

URL 解码必须经过 schema 或显式解析函数，不直接信任字符串。

## 9. HTTP 与 API 契约

### 9.1 纯 HTTP Client

目标 client 不直接导入 store：

```ts
interface HttpClientOptions {
  baseUrl: string;
  getAccessToken?: () => string | null;
  onResponse?: (response: Response) => void;
  onError?: (error: ApiError) => void;
}
```

职责：

- URL 与 query string。
- JSON/FormData 编码。
- Cookie/Bearer。
- AbortSignal。
- 错误归一化。
- request ID 提取。
- 非 JSON 响应。

不负责：

- toast 文案。
- 组卷网横幅。
- 页面跳转。
- Query cache。
- 任务事件解释。

业务提示由 app observer 或 feature mutation handler 处理。

### 9.2 OpenAPI 生成

保留现有：

- `scripts/export_openapi.py`。
- `scripts/split_openapi_types.py`。

目标流程：

```text
FastAPI schema
  -> filtered /api OpenAPI
  -> generated TypeScript contracts
  -> domain adapter
  -> queryOptions / mutation
```

FastAPI 官方支持从 OpenAPI 生成 TypeScript SDK：

- [Generating SDKs](https://fastapi.tiangolo.com/advanced/generate-clients/)

鉴于当前存在大量泛化 `dict` response model：

- 生成类型先作为底线。
- 高风险 REST 结果在领域边界进行运行时解码。
- 新增或修改的后端接口应优先使用明确 Pydantic response model。
- SSE 契约继续单独维护，不假设 OpenAPI 能表达完整事件流。

### 9.3 Query Options

每个领域集中定义：

```ts
export const paperQueries = {
  all: () => ["papers"] as const,
  list: (filters: PaperFilters) =>
    queryOptions({
      queryKey: [...paperQueries.all(), "list", filters],
      queryFn: () => papersApi.list(filters),
    }),
  detail: (paperId: number) =>
    queryOptions({
      queryKey: [...paperQueries.all(), "detail", paperId],
      queryFn: () => papersApi.get(paperId),
    }),
};
```

同一 query options 用于：

- `useQuery`。
- route loader prefetch。
- invalidation。
- optimistic update。
- 测试。

## 10. Task 与 Streaming 架构

### 10.1 当前协议事实

当前至少存在以下事件载荷族：

1. Chat 扁平事件：`{type, ...payload}`。
2. 持久任务信封：`{taskId, seq, type, data, created_at}`。
3. 直接 agent event：`{event, data, trace_id?}`。
4. 局部 section stream：`{type, seq, data}`。

另外：

- 部分 POST 流以 `[DONE]` 结束。
- task stream 使用 `after_seq`，而不是浏览器 `Last-Event-ID`。
- paused、pending_review 或 terminal 都可能直接 EOF。
- 后端不保证 EOF 前一定有 `done/result/error`。
- backlog truncated 可能使用 `type: error` 提示后继续发送事件。
- 同名 `text_delta` 在不同领域可能分别表示增量或完整快照。

因此不能使用一个“按事件名猜语义”的通用 reducer。

### 10.2 分层

```text
bytes
  -> SSE frame parser
  -> transport
  -> envelope adapter
  -> runtime schema decoder
  -> domain event
  -> pure reducer
  -> task registry projection
  -> UI
```

#### Frame Parser

只负责：

- `\n\n` / `\r\n\r\n` 分帧。
- 合并多行 `data:`。
- 处理 `[DONE]`。

#### Transport

分为：

- `postSse()`：fetch + ReadableStream。
- `taskEventSource()`：EventSource + `after_seq`。
- 可选 `taskWebSocket()`：仅作为未来 fallback。

#### Envelope Adapter

把 wire payload 转成：

```ts
type RawStreamEvent =
  | { source: "chat"; type: string; payload: unknown }
  | { source: "task"; taskId: string; seq: number; type: string; data: unknown }
  | { source: "agent"; event: string; data: unknown; traceId?: string };
```

#### Domain Decoder

每个 feature 定义判别联合并使用 `unknown` 作为输入，禁止在边界使用 `any`。

#### Pure Reducer

领域 reducer 不持有连接对象，不执行 fetch，不显示 toast，输入 event，输出新状态和 effect 描述。

### 10.3 Task Coordinator

Task Coordinator 负责：

- 按 task ID 注册任务。
- 保持 route 卸载后的追踪。
- 保存 `lastSeq`。
- 去重和乱序保护。
- 建立/关闭连接。
- 指数退避重连。
- EOF 后 REST 校准。
- 终态后触发领域 query invalidation。
- 为 UI 提供稳定 selector。

连接 handle 存放在 registry 内部，不进入可序列化 store。

### 10.4 状态机

```text
idle
  -> submitting
  -> running
  -> reconnecting
  -> running

running
  -> paused
  -> pending_review
  -> completed
  -> failed
  -> canceled

paused
  -> running
  -> failed
  -> canceled

pending_review
  -> running
  -> completed
  -> failed
  -> canceled
```

关键规则：

- EOF 不是 completed。
- EventSource `onerror` 不是 failed。
- `type: error` 不一定是终态。
- EOF 或连接失败后先 GET task status。
- `status === running` 才重连。
- `paused` 和 `pending_review` 保留投影并停止连接。
- terminal 才释放连接并触发结果查询。

### 10.5 鉴权

同源 EventSource 依赖 HttpOnly Cookie，因为原生 EventSource 不能设置自定义 `Authorization` header。

因此：

- 同源 SSE 是默认任务通道。
- Bearer 只作为普通 HTTP/POST stream 的补充。
- WebSocket 在后端支持 Cookie 握手前不作为默认通道。
- 不把 JWT 放在 URL 查询参数作为长期方案。

## 11. Zustand 使用边界

保留 Zustand，但限制为：

- theme。
- sidebar。
- global search dialog。
- toast queue。
- 与页面无关的轻量 UI preference。

Task Coordinator 可以使用 Zustand 暴露只读投影，但连接、协议解码和 reducer 不应与 Zustand API 耦合。

不得放入 Zustand：

- REST 列表。
- REST 详情。
- 查询 loading/error。
- 可由 URL 表达的筛选。
- 领域 API client。

## 12. UI 与设计系统

保留当前：

- Tailwind CSS v4。
- Radix primitives。
- CVA。
- 双主题 token。
- Markdown/KaTeX 渲染能力。

重构边界：

- `shared/ui`：无业务语义的 primitive。
- `entities/*/ui`：PaperCard、QuestionCard 等实体展示。
- `features/*/ui`：审核面板、生成配置、任务操作等业务组件。
- `app/shell`：导航、顶栏、全局搜索和 banner。

禁止把业务 API、Query 或 store 引入 `shared/ui`。

## 13. 测试与质量门禁

### 13.1 单元与组件测试

建议：

- Vitest。
- React Testing Library。
- MSW。
- fake EventSource / 可注入 transport。

优先测试：

1. SSE parser 的分块和多行 data。
2. envelope adapter 的 `type/event` 兼容。
3. task reducer 的 seq 去重。
4. backlog truncated 后继续。
5. EOF 后状态校准。
6. pending_review。
7. paused/resume。
8. materials snapshot 替换语义。
9. chat delta 追加语义。
10. API error 和 request ID。

### 13.2 端到端测试

Playwright 只覆盖高价值闭环：

- 本地用户/登录启动。
- 创建对话并接收流。
- 发起长任务、刷新页面、从 `after_seq` 恢复。
- paper compose 进入 pending_review 并提交审核。
- 生成文件下载与 410 过期提示。

### 13.3 契约检查

CI 或 doctor 增加：

```text
export OpenAPI
  -> generate contracts
  -> verify generated tree clean
```

SSE 使用固定真实事件 fixture，不从已删除前端恢复 fixture。

### 13.4 构建检查

至少执行：

- `npm run lint`。
- `npm run test`。
- `npm run build`。
- route chunk 报告。
- touched-path `git diff --check`。

## 14. 迁移计划

### Phase 0：基线与护栏

目标：

- 固定现有操作流。
- 不改变 UI。

工作：

- 增加 Vitest、Testing Library、MSW。
- 为 `SseParser`、当前 task reducer 和错误归一化增加 characterization tests。
- 保存当前 build chunk 和关键路由清单。
- 明确同源部署为 canonical path。

完成条件：

- `npm run test` 可运行。
- 当前 parser/reducer 行为有测试记录。
- build/lint/test 全绿。

### Phase 1：App 与 Shared 基础设施

工作：

- 新建 `app/`、`shared/`。
- 提取 QueryClient 配置。
- 建立纯 HTTP client。
- 打破 `auth store <-> api client` 循环依赖。
- 建立统一 error observer。
- 建立 route catalog。

完成条件：

- `shared/api` 不导入 store。
- route、sidebar、title 来自单一 catalog。
- 用户可见行为不变。

### Phase 2：路由拆分

工作：

- 为业务路由增加 lazy。
- 增加 shell/public/feature error boundary。
- 将页面筛选逐步放入 URL。
- loader 只做关键 Query 预取。

完成条件：

- Vite 输出多个业务 route chunk。
- 初始 shell 不同步导入全部页面。
- 深链刷新仍由 FastAPI SPA fallback 正常工作。

### Phase 3：Streaming 与 Task Coordinator

工作：

- 拆分 parser、transport、adapter、decoder、reducer。
- 建立 task registry。
- 支持 `lastSeq`、重连、EOF 状态校准。
- 将 non-terminal error 与 terminal failure 分开。
- 统一 terminal 后 query invalidation。

完成条件：

- task 生命周期不再由页面各自实现。
- route 卸载不会丢失活动任务。
- pending_review/paused 不被误判为完成或失败。
- 真实事件 fixture 覆盖所有载荷族。

### Phase 4：迁移示范 Feature

首选 `study-materials`。

原因：

- 同时覆盖 REST、POST SSE、任务恢复、快照文本、归档和导出。
- 已经暴露通用 reducer 无法统一 snapshot/delta 的问题。
- 能验证目标架构的大多数关键边界。

完成条件：

- `routes/materials.route.tsx` 仅装配。
- API、query、stream decoder、reducer 和 UI 分离。
- 现有生成、继续、恢复、归档和导出流不变。

### Phase 5：迁移大型 Feature

顺序：

1. question-library。
2. paper-compose。
3. task-center。
4. chat。
5. papers。
6. settings 和其他较独立页面。

每次只迁移一个 feature，并保留相同路由和行为。

### Phase 6：契约生成与后端 schema 收敛

工作：

- 生成 REST contracts。
- 为高风险泛化响应补 Pydantic schema。
- 新增 schema drift check。
- SSE 保持单独 runtime schema。

完成条件：

- 手写 API DTO 显著减少。
- 新增 API 必须有明确 response model 或记录例外原因。
- 前后端契约漂移能在 CI 中失败。

### Phase 7：版本升级

架构迁移稳定后再单独评估：

- React 19。
- React Router 8。
- Vite 7/8。

React Router 8 当前最低要求包括 Node 22.22+ 和 React 19.2.7+；Framework Mode 还要求 Vite 7+。版本升级不得与 feature 搬迁合并为一次大改动。

官方资料：

- [Updating from React Router v7](https://reactrouter.com/upgrading/v7)

## 15. 验收标准

架构迁移完成应满足：

### 结构

- 页面/route 文件只负责 URL 和装配。
- 复杂业务全部进入 feature。
- 路由、导航、标题只有一个真源。
- 依赖方向符合 `app -> routes -> features -> entities -> shared`。
- shared HTTP/UI 不依赖业务 store。

### 状态

- REST 状态只由 TanStack Query 持有。
- 筛选、分页、tab 和选中实体可从 URL 恢复。
- Zustand 不复制 REST 数据。
- task stream 具有显式状态机。

### 流式协议

- 支持所有当前载荷族。
- 支持 `after_seq`。
- EOF 后按 REST 状态校准。
- 非终态 error 不会提前关闭任务。
- snapshot/delta 由领域 decoder 决定。

### 构建

- 业务路由被拆成独立 chunk。
- 主入口不再包含所有页面。
- build、lint、unit tests、关键 E2E 全绿。

### 契约

- REST 类型可由 OpenAPI 再生成。
- 高风险响应具有运行时校验或明确 Pydantic schema。
- request ID 能进入错误诊断界面。

### 用户体验

- 现有 URL 不变。
- 现有操作流不变。
- 刷新后活动任务可恢复。
- pending_review 不丢失。
- 视觉样式无非预期回归。

## 16. 风险与缓解

| 风险 | 缓解 |
| --- | --- |
| 一次性目录搬迁造成大面积回归 | 逐 feature 迁移，每阶段可独立验证和回滚 |
| SSE 重构改变隐含兼容行为 | 先增加 characterization tests 和真实事件 fixture |
| OpenAPI 生成给出虚假类型安全 | 保留 domain adapter，逐步补 Pydantic schema |
| route lazy 引入加载闪烁 | 统一 pending UI，预取高频路由 |
| URL 状态迁移改变默认行为 | 先保持现有默认值，再增加解析与回归测试 |
| HTTP client 解耦后提示丢失 | 建立 app-level error observer 和 feature error mapping |
| 版本升级扩大范围 | React/Router/Vite 升级单独排期 |
| clean-room 边界被误触 | 禁止历史 frontend Git 读取，fixture 只来自当前后端和当前实现 |

## 17. 回滚策略

- 每个 Phase 独立提交和验证。
- feature 迁移期间保留旧 route wrapper，只切换内部实现。
- transport 和 reducer 通过 adapter 并行接入，不同时删除兼容路径。
- route lazy 可按路由单独回退为同步 import。
- API 生成先作为类型来源，不立即删除手写 adapter。
- 不改变后端任务或数据库 schema，避免跨层回滚。

## 18. 当前验证快照

本提案形成时已执行：

- `npm run build`：通过。
  - 2,070 modules transformed。
  - 主 JS：1,167.32 kB。
  - gzip：352.83 kB。
- `npm run lint`：0 error。
  - 2 个既有 Fast Refresh warning：
    - `src/components/ui/badge.tsx`。
    - `src/components/ui/button.tsx`。
- OpenAPI 导出：成功。
  - 185 operations。
  - 81 component schemas。
- 当前没有可运行的前端测试套件。

这些结果只是迁移前快照，不表示本提案已经实施。

## 19. 最终决策

采用：

> **Vite + React + React Router Data Mode + TanStack Query + Zustand，重构为 feature-sliced 的领域模块化 SPA，并建立独立 Task/Stream Coordinator。**

当前不采用：

- React Router Framework Mode。
- TanStack Router。
- Next.js。
- TanStack Start。
- Astro。
- 通用 CRUD 管理后台框架。

重新评估基础框架的触发条件：

- SEO/公开内容成为主要产品目标。
- 需要真正的服务端渲染或边缘渲染。
- 前端需要独立于 FastAPI 部署并拥有明确 BFF 职责。
- 类型安全 URL 状态成为持续性高成本问题。
- 当前 Data Mode 在完成模块化后仍有明确、可测量的阻塞。

在这些条件出现前，优先解决已经确认的结构、契约、流式状态和测试问题。
