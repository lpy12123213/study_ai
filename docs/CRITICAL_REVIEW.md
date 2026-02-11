# 项目批判性审查报告

> 审查日期：2026-02-11

---

## 一、安全问题（严重）

### 1. 大量 API 端点无认证保护

只有 `chat` 和 `conversations` 路由加了 `require_auth`。以下端点完全裸露：

- `/api/papers/*` — 任何人可创建/删除试卷
- `/api/deepthink` — 直接调用 AI 模型，消耗 API 额度
- `/api/canvas/*` — 读写画布数据
- `/api/crawler-tools/*` — 直接触发爬虫请求
- `/api/study-materials/tasks/{task_id}/stream` — 任何人可通过 task_id 窥探他人生成内容
- `/api/subjects`、`/api/models` — 泄露系统配置

`study_materials/generate` 用了 `get_current_user`（可选认证），未登录时 user_id 降级为 `"anonymous"`，但仍然允许调用，等于没有保护。

**位置**: `backend/api/` 下的 `papers.py`、`deepthink.py`、`canvas.py`、`crawler_tools.py`、`study_materials.py`

### 2. 命令注入风险

`backend/crawler/zujuan_crawler.py` 第 3815 行附近：

```python
cmd = f'start "组卷网登录" cmd /c "python \"{py_path}\" --subject \"{self.subject}\""'
subprocess.Popen(cmd, shell=True)
```

`self.subject` 来自用户输入（`set_subject` 工具），如果传入恶意字符串可注入任意命令。`shell=True` + f-string 拼接是经典的命令注入模式。

**修复建议**: 使用列表形式传参 + `shell=False`，或对 `self.subject` 做白名单校验（只允许 `SUBJECTS` 字典中的合法值）。

### 3. CORS 全开

```python
allow_origins=["*"],
allow_credentials=True,
```

`allow_origins=["*"]` 配合 `allow_credentials=True` 意味着任何网站都可以尝试带凭据发起跨域请求。虽然浏览器会拒绝 `*` + credentials 的组合，但配置意图本身就是错误的。

**位置**: `backend/app.py`

**修复建议**: 开发环境用 `["http://localhost:3000"]`，生产环境用实际域名。

### 4. 密码用 SHA256 裸哈希

```python
def hash_password(password: str) -> str:
    return hashlib.sha256((password or "").encode()).hexdigest()
```

没有 salt，没有 bcrypt/scrypt/argon2。彩虹表可以秒破。

**位置**: `backend/auth.py`

**修复建议**: 使用 `bcrypt` 或 `passlib`。

### 5. 用户存储在内存中

`backend/auth.py` 的 `_users` 是一个 dict，重启即丢失。注册的用户、改过的密码全部消失。

**修复建议**: 将用户表迁移到 SQLite 数据库。

### 6. SQL 注入风险（LIKE 通配符）

`backend/database/models.py` 第 588 行：

```python
stmt = stmt.where(CanvasBoard.title.like(f"%{query}%"))
```

虽然 SQLAlchemy 的 `like()` 会参数化防止真正的 SQL 注入，但 `%` 和 `_` 是 LIKE 通配符，用户可以传 `%` 匹配所有记录，或用 `_` 做模式探测。

**修复建议**: 转义 LIKE 特殊字符（`%` → `\%`，`_` → `\_`）。

---

## 二、架构问题

### 1. 爬虫文件 3847 行，严重违反单一职责

`zujuan_crawler.py` 包含：Cookie 管理、反爬绕过、HTTP 客户端、HTML 解析、公式转换（MathML→LaTeX via pandoc）、题目缓存、省份解析、蓝图组卷、题篮导出、登录窗口启动……全部塞在一个类里。

`backend/crawler/` 下已有 `auth.py`、`base.py`、`cache.py`、`constants.py`、`parsers.py`、`utils.py`，但 `zujuan_crawler.py` 似乎没有真正使用这些拆分模块，两套代码并存。

### 2. 模块重复

| 重复项 | 位置 A | 位置 B | 说明 |
|--------|--------|--------|------|
| 学科配置 | `backend/subjects.py` | `backend/core/subjects.py` | 同一份配置两个位置 |
| 应用配置 | `backend/config.py` | `backend/core/settings.py` | config.py 是"兼容层"，重构未完成 |
| MCP 工具注册 | `backend/mcp/server.py` | `backend/mcp/stdio_server.py` | 两套独立的工具注册，不共享 |

### 3. 全局单例 crawler 的并发问题

`crawler_manager.py` 维护一个全局 `_crawler`。当两个请求同时到达且需要不同学科时：

```python
if _crawler.subject != resolved_subject:
    _crawler.set_subject(resolved_subject)  # 竞态条件
```

`set_subject` 会清空所有元数据缓存，正在进行的另一个请求会拿到空的映射表。没有锁，没有 per-request 隔离。

**修复建议**: 加 asyncio.Lock，或改为 per-subject 实例池。

### 4. MCP stdio_server 的 `_register_handlers` 方法过长

整个工具注册 + 调用分发写在一个方法里（超过 1800 行），是一个巨大的 if-elif 链。

**修复建议**: 用注册表模式或装饰器模式拆分。

---

## 三、代码质量问题

### 1. 死代码

`_fetch_csrf_token_from_page` 函数在 `return None` 之后还有一大段代码（第 230-250 行附近），永远不会执行。这是复制粘贴遗留。

**位置**: `backend/crawler/zujuan_crawler.py`

### 2. 没有测试

AGENTS.md 明确写了 "There is no dedicated test suite"。一个有 3800 行爬虫、多个 AI 调用链、数据库操作的项目，零测试覆盖。smoke check 只验证 import 不报错。

### 3. 假流式输出

`chat_service.py` 第 1530 行附近：

```python
chunk_size = 10
for i in range(0, len(final_content), chunk_size):
    yield {"type": "text_delta", "content": final_content[i:i+chunk_size]}
    await asyncio.sleep(0.02)  # 小延迟模拟打字效果
```

当 AI 没有调用工具时，已经拿到了完整响应，却人为切成 10 字符一块、加 20ms 延迟"模拟打字"。一个 2000 字的回复要多等约 4 秒。

**修复建议**: 非工具调用场景直接用流式 API（`stream=True`），或一次性返回完整内容。

### 4. 异常吞没

爬虫中大量 `except Exception: return`、`except Exception: pass`，错误被静默吞掉。调试时完全看不到失败原因。

**修复建议**: 至少加 `logging.exception()` 或 `logging.warning()`。

### 5. `asyncio.get_event_loop()` 已废弃

爬虫中多处使用 `asyncio.get_event_loop()`，在 Python 3.10+ 中会抛 DeprecationWarning，3.12+ 行为更严格。

**修复建议**: 改用 `asyncio.get_running_loop()`。

---

## 四、可靠性问题

### 1. Cookie 过期无自动恢复

爬虫初始化时获取 Cookie，之后复用。如果 Cookie 在运行中过期（TTL 6 小时），后续所有请求都会失败，直到手动重启服务。没有自动刷新机制。

### 2. AI 工具调用循环没有成本控制

`MAX_TOOL_ITERATIONS` 默认 10 轮，每轮最多 3 个工具调用，每个工具调用可能触发多次 HTTP 请求（爬虫翻页）。一次用户对话可能产生 30+ 次外部 API 调用，没有任何费用预警或限制。

### 3. 内存中的任务管理器

`StudyMaterialsTaskManager` 把所有任务和事件存在内存里。服务重启后所有进行中的任务丢失，客户端会永远等待一个不存在的 task_id。

### 4. 无 Rate Limiting

`backend/crawler/constants.py` 定义了 `RATE_LIMIT_REQUESTS_PER_SECOND = 2`，但搜索整个代码库没有找到任何实际使用这个常量的地方。API 层面也没有任何请求频率限制。

---

## 五、优先级建议

| 优先级 | 问题 | 影响 |
|--------|------|------|
| P0 | 命令注入（subprocess + shell=True） | 远程代码执行 |
| P0 | API 端点无认证 | 未授权访问、API 额度滥用 |
| P1 | 密码裸哈希 | 用户凭据泄露 |
| P1 | 全局 crawler 并发竞态 | 跨学科数据错乱 |
| P1 | 补充基础测试 | 回归风险 |
| P2 | 拆分爬虫模块 | 可维护性 |
| P2 | 清理模块重复 | 代码一致性 |
| P2 | Cookie 自动刷新 | 服务可用性 |
| P3 | 假流式输出优化 | 用户体验 |
| P3 | 异常吞没改为日志 | 可调试性 |
