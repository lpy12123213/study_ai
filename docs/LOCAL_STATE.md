# 本地运行时目录（`.local/`）

为避免项目根目录堆满数据库、缓存、调试截图、Playwright 浏览器数据等“只和本机有关”的文件，本项目将这些内容统一放到 `.local/` 下（并在 `.gitignore` 中忽略）。

## 目录用途

推荐的本地目录结构如下：

```
.local/
├── exam_papers.db                 # SQLite 数据库（只存题号/元数据）
├── cache/
│   └── zujuan_antibot_cookies.json # 反爬 Cookie 缓存（减少重复初始化）
├── artifacts/                     # 调试产物（截图/HTML/JSON 等）
├── playwright/
│   └── zujuan_user_data/          # Playwright 持久化用户数据（登录态）
└── data/                          # 本地数据/备份（可选）
```

## 兼容旧路径

如果你之前已经运行过旧版本，可能存在以下目录/文件：

- `exam_papers.db`（仓库根目录）
- `.cache/`
- `artifacts/`
- `data/`
- `.playwright_zujuan_user_data/`

代码层面已做兼容：当 `.local/` 不存在对应文件时，会回退到旧路径（或在可移动时迁移）。

## 迁移与清理

### 迁移旧目录到 `.local/`（推荐）

运行：

```bash
python scripts/organize_local_state.py migrate
```

说明：
- 该脚本只移动本地文件，不会修改代码。
- 如果 `exam_papers.db` 被正在运行的后端占用，脚本会提示你先停止 `uvicorn` 后再迁移。

### 清理本地运行时文件

如果你想“彻底重置本地状态”（例如重新登录、重新抓取、清空数据库），可以删除整个目录：

```bash
rm -rf .local
```

然后重新启动服务即可自动重新初始化数据库。

