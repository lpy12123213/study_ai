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
- Docker：推荐用于 LaTeX PDF 沙盒编译。
- `dvisvgm`：TikZ/PGF 转 SVG。
- Asymptote `asy`：部分图形回退。
- Pandoc：DOCX 导出。

Windows 上建议安装 MiKTeX 或 TeX Live，并确认相关可执行文件在 `PATH` 中。公网或多用户部署建议优先启用
Docker LaTeX 沙盒：

```bash
docker build -t study-ai/latex-sandbox:latest docker/latex-sandbox
```

`.env` 中保持 `PAPER_EXPORT_LATEX_BACKEND=auto` 可在镜像存在时走沙盒、镜像缺失时回退宿主机；如需强制沙盒，
设为 `docker`。可用 `LATEX_SANDBOX_MEMORY`、`LATEX_SANDBOX_CPUS`、`LATEX_SANDBOX_PIDS_LIMIT`
限制容器资源。

## 部署模型

当前支持并维护的部署模型：

- 本地开发：Vite 前端 + Uvicorn 后端。
- 同源部署（默认）：后端托管 `frontend/dist`，浏览器使用相对 `/api`，无需设置 `VITE_API_BASE_URL`。
- 跨站部署：前端构建时设置 `VITE_API_BASE_URL` 指向后端 origin，后端开启 `CORS_ORIGINS` allowlist 与 `AUTH_COOKIE_SAMESITE=none`。

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

前端与后端之间有两种受支持的模式。

### 模式一：同源反向代理（推荐）

前端构建产物放在 `frontend/dist`，由后端同时托管静态资源与 `/api`，浏览器使用相对地址，不会遇到跨域问题。此模式无需设置 `VITE_API_BASE_URL`（默认），认证 Cookie 使用 `SameSite=Lax`。

### 模式二：跨站部署

前端与后端分别托管在不同 origin（例如前端 `https://app.example.com`、后端 `https://api.example.com`）。前端、后端与 Cookie 需要一起配置：

- 前端构建时把 `VITE_API_BASE_URL` 设为后端 origin，所有 REST、下载、POST SSE、EventSource 与 WebSocket 请求都会指向该地址。
- 后端用 `CORS_ORIGINS` 白名单只允许前端 origin，并为跨站请求开启携带凭证。
- 设置 `AUTH_COOKIE_SAMESITE=none`：`none` 隐含 `Secure`，因此跨站部署必须启用 HTTPS。
- 前端跨站请求使用 `credentials: include`，EventSource 使用 `withCredentials`，才能携带认证 Cookie。

注意：`CORS_ORIGINS=*` 与携带凭证的请求不能同时使用（`*` + 凭证的 CORS 组合无效），必须显式列出前端 origin。

```bash
VITE_API_BASE_URL=https://api.example.com   # 前端构建时
AUTH_COOKIE_SAMESITE=none                    # 后端；隐含 Secure，要求 HTTPS
CORS_ORIGINS=https://app.example.com         # 后端 allowlist
```

修改 `VITE_API_BASE_URL` 后重新构建前端：

```bash
cd frontend
npm run build
```

开发环境下跨站分离仍走 Vite dev proxy（`VITE_DEV_PROXY_TARGET`），不涉及跨站 Cookie。

### 部署相关环境变量

| 变量 | 位置 | 说明 |
| --- | --- | --- |
| `VITE_API_BASE_URL` | 前端构建时 | 后端 origin；默认留空表示同源相对 `/api` |
| `VITE_DEV_PROXY_TARGET` | 前端开发 | Vite dev server 的 `/api` 代理目标，默认 `http://localhost:8000` |
| `AUTH_COOKIE_SAMESITE` | 后端 | `lax`（默认）或 `none`；`none` 隐含 `Secure`，跨站部署需要 HTTPS |
| `CORS_ORIGINS` | 后端 | 允许跨站访问的 origin allowlist，逗号分隔 |

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
- `config/model.json` 中的 provider、路由、模型 ID 和密钥已按部署环境配置。
- 不允许提交真实 API key、Cookie、数据库、抓取内容。
- 只开启必要的 `PAPER_STORE_*` 内容持久化。
- 多用户部署中 PDF 导出优先使用 `PAPER_EXPORT_LATEX_BACKEND=docker` 或确认 `auto` 能找到沙盒镜像。
- 媒体代理域名白名单符合预期。
- 反向代理正确处理 SSE。
- 日志不会输出密钥明文。

## 备份与恢复

需要保留的本地状态通常包括：

- `.local/` 下的 SQLite 数据库和任务事件。
- `.local/media/generated/` 下仍需下载的导出文件。
- `study_archives/` 下的学习资料归档。
- `config/model.json`：唯一的模型配置源，包含 provider 密钥，但不应提交到 Git。
- `.local/secrets/model_config.key`：如果 `model.json` 使用加密密钥，恢复时必须与配置文件成对保留。

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

恢复时必须先确认 `.env`、`config/model.json`、模型解密密钥和数据库 schema 与目标版本兼容。

建议生产或长期运行环境至少每日备份一次，并保留最近 7 到 14 天的数据库副本。Linux 可使用 cron：

```cron
15 3 * * * cd /opt/study_ai && .venv/bin/python scripts/backup_db.py --output-dir /var/backups/study_ai/db --name nightly
```

Windows 服务器可用“任务计划程序”每日运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "Set-Location C:\study_ai; .\venv\Scripts\python.exe scripts\backup_db.py --output-dir C:\study_ai-backups\db --name nightly"
```

备份目录应位于应用目录之外或同步到外部存储。清理旧备份时只删除确认可恢复窗口之外的文件，并至少保留最近一次上线前备份。

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
