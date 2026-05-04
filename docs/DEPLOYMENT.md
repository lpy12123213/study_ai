# 部署与运行

本文覆盖本地运行、构建、同源部署、反向代理和上线前检查。项目默认适合本地或内网部署；公网部署前必须检查密钥、鉴权、代理、SSE 和数据持久化策略。

## 环境要求

必需：

- Python 3.10+
- Node.js LTS
- npm
- Playwright Chromium

按需：

- XeLaTeX 或 PDFLaTeX：PDF 导出。
- `dvisvgm`：TikZ/PGF 转 SVG。
- Asymptote `asy`：部分图形回退。
- Pandoc：DOCX 导出。

Windows 上建议安装 MiKTeX 或 TeX Live，并确认相关可执行文件在 `PATH` 中。

## 部署模型

当前支持并维护的部署模型：

- 本地开发：Vite 前端 + Uvicorn 后端。
- 同源部署：后端托管 `frontend/dist`，浏览器使用 `/api`。
- 前后端分离部署：前端设置绝对 `VITE_API_BASE_URL`。

当前不提供正式容器化生产入口。容器化部署需要另行维护 Dockerfile、卷、健康检查和 CI 验证。

## 推荐流程

Windows：

```bat
start.bat setup
start.bat doctor
start.bat dev
```

Linux / macOS：

```bash
chmod +x start.sh
./start.sh setup
./start.sh doctor
./start.sh dev
```

`setup` 会根据依赖文件指纹安装后端和前端依赖；依赖变化后可以重复运行。

## 手动构建

后端：

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m playwright install chromium
```

Windows 激活虚拟环境：

```bat
venv\Scripts\activate
```

前端：

```bash
cd frontend
npm install
npm run lint
npm run build
cd ..
```

启动后端：

```bash
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

启动 MCP：

```bash
python -m backend.mcp.stdio_server
```

## 前端部署方式

### 同源部署

推荐同源部署：前端构建产物放在 `frontend/dist`，API 使用默认 `/api`。后端可以同时服务静态资源和 API，浏览器不会遇到跨域问题。

### 前后端分离

如果前端独立托管：

```bash
VITE_API_BASE_URL=https://your-backend.example/api
```

然后重新构建前端：

```bash
cd frontend
npm run build
```

后端需要允许对应来源访问，并确认 SSE 不被代理缓冲。

## 反向代理

Nginx / Caddy / Traefik 需要注意：

- `/api/` 转发到 FastAPI。
- SSE 路径关闭响应缓冲。
- 静态资源正常缓存。
- WebSocket 不是主路径，但 SSE 长连接必须保持。

如果需要信任代理传入的客户端 IP：

- `TRUST_PROXY_HEADERS=1`
- `TRUSTED_PROXIES=127.0.0.1,10.0.0.0/8`

只在受信任的网络边界开启，不要在未知代理后使用 `*`。

## 数据目录

常见本地状态：

- `.local/`：SQLite、媒体缓存、任务事件、内部状态。
- `.local/media/generated/`：导出文件和生成媒体。
- `study_archives/`：自学资料归档。
- `artifacts/`、`output/`：本地检查、导出或调试产物。
- `data/`：本地数据。

这些目录默认不应提交。

## 安全检查

上线前至少确认：

- `.env` 中的 `JWT_SECRET`、`ADMIN_PASSWORD` 已更换。
- 不允许提交真实 API key、Cookie、数据库、抓取内容。
- 只开启必要的 `PAPER_STORE_*` 内容持久化。
- 媒体代理域名白名单符合预期。
- 反向代理正确处理 SSE。
- 日志不会输出密钥明文。

## 备份与恢复

需要保留的本地状态通常包括：

- `.local/` 下的 SQLite 数据库和任务事件。
- `.local/media/generated/` 下仍需下载的导出文件。
- `study_archives/` 下的学习资料归档。
- 自定义 `config/model.json`，但不应把密钥提交到 Git。

SQLite 数据库使用项目自带脚本备份。备份通过 `VACUUM INTO` 生成一致性副本，不需要直接复制正在写入的数据库文件：

```bash
python scripts/backup_db.py --name before-upgrade
```

默认输出目录是 `.local/backups/db/`。如需指定数据库或输出目录：

```bash
python scripts/backup_db.py --db-path .local/exam_papers.db --output-dir .local/backups/db
```

恢复前必须停止后端进程，避免运行中的 SQLite 连接继续写入旧 WAL。恢复命令默认拒绝覆盖，必须显式确认：

```bash
python scripts/restore_db.py .local/backups/db/exam_papers-YYYYMMDD-HHMMSS.db --yes
```

如果目标数据库已经存在，恢复脚本会先生成 `*.pre-restore-*.db` 安全副本，再覆盖目标库，并在恢复后运行 `PRAGMA integrity_check`。

恢复时必须先确认 `.env`、模型配置和数据库 schema 与目标版本兼容。

## 上线前验证

```bash
start.bat doctor
```

或：

```bash
./start.sh doctor
```

`doctor` 会运行：

- Python 编译检查。
- 后端关键 import。
- `pip check`。
- 后端单元测试。
- Ruff 维护路径检查。
- 前端 lint。
- 前端构建。

如果部署环境不安装 dev 依赖，可在 CI 或构建机运行完整检查，再把构建产物和运行依赖部署到目标环境。

## 当前不包含

仓库当前没有可直接使用的官方 Docker/Compose 生产部署入口。需要容器化时，应新增真实维护的 Dockerfile、健康检查、卷挂载、环境变量文档和 CI 验证。

## 相关文档

- `CONFIGURATION.md`：环境变量和模型配置。
- `TROUBLESHOOTING.md`：运行故障排查。
- `API.md`：健康检查、任务流和接口路径。
