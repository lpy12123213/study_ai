# 前端布局结构重写：完成 Master-Detail 改造（已完成 2026-06-13）

对应 nextstep.csv 第 41/42 行的后半程收尾。前半程（2026-06-05）已落地嵌套路由 + WorkspaceSplitLayout；本次解决遗留的移动端断裂、列表重复、study-archives 残缺等问题。视觉沿用 Aurora Glass，URL 路径全部不变。

## 改动清单

### 1. 死代码清理
删除 0 引用文件：
- `frontend/src/pages/{papers,lesson-plans,study-archives,ai-generate}/` 下 7 个旧 wrapper（引用已不存在的旧 API）
- `frontend/src/components/layout/TaskPanel.tsx`

### 2. 面包屑统一派生
- `SubHeader.tsx` 改用 `useRouteMeta()`（useMatches handle 优先、pathname fallback），与 ManusLayout/Header 一致
- `routes.config.ts` 新增 `study-archives` 父配置（label「学习档案」，navGroup secondary），`study-archive-detail` 接上 parentId
- `getRouteCrumbs(pathname, route?)` 支持传入已解析的 routeConfig
- `router/index.tsx` study-archives 父路由补 `handle('study-archives')`

### 3. 移动端两屏切换（lg=1024px 断点）
`WorkspaceSplitLayout.tsx` 用 `useParams()` 判定是否在详情子路由：
- 列表态：左栏 `flex w-full`（移动端全宽），主区 `hidden lg:block`
- 详情态：左栏 `hidden lg:flex`，主区 `block`
- 详情页已有返回按钮；StudyArchiveDetailPage 返回链接由 `/study-materials` 改为 `/study-archives`

### 4. papers 打样（消灭双列表）
- 新建 `features/workspace/papers/PapersMasterList.tsx`：左栏完整 master 列表（搜索、标签过滤、置顶优先排序、星标/置顶指示、DropdownMenu 操作：答题/收藏/置顶/标签/删除），含删除确认与 TagEditDialog；在 WorkspaceSplitLayout 内 lazy 加载
- 新建 `features/workspace/papers/usePaperMeta.ts`：共享 meta（星标/置顶/标签）query + mutation
- `pages/PapersPage.tsx` 瘦身为概览 index（hero + stats + 空态引导），不再渲整表
- 新建 `features/workspace/useMasterList.ts`：通用左栏取数 hook（lesson-plans / study-archives），react-query 维持现状（不迁 router loader——与 lazy/Suspense 及 query 缓存失效体系冲突）

### 5. 区块推广
- 通用左栏（GenericMasterList）加搜索框
- 新建 `pages/StudyArchivesIndexPage.tsx`（档案概览/空态），替换原 `/study-archives` → `/study-materials` 的 redirect
- ai-generate 摘除伪 split（左栏只有一条硬编码项），改为平铺路由，路径不变

### 6. 测试
- 新增 `router/__tests__/routes.config.test.ts`：HEADER_NAV 派生稳定、study-archives 匹配、两级面包屑
- 新增 `components/layout/__tests__/WorkspaceSplitLayout.test.tsx`：createMemoryRouter 嵌套路由，断言列表态/详情态显隐
- 全量：69 文件 195 测试通过，build 通过，本次改动文件 eslint 零告警

## 行为变化

- `/study-archives` 从 redirect 变为真实列表页（概览 + 左栏档案列表）
- `<1024px` 下 split 区块从"无列表入口"变为列表/详情两屏切换
- 学习档案出现在 secondary 导航与命令面板
