# Cherry Studio MCP 服务配置教程

本教程将指导你在 Cherry Studio 中配置和使用「智能组卷辅助系统」的 MCP 服务。

## 目录

- [前置准备](#前置准备)
- [配置 MCP 服务](#配置-mcp-服务)
- [验证服务连接](#验证服务连接)
- [使用 MCP 工具](#使用-mcp-工具)
- [常用指令示例](#常用指令示例)
- [常见问题排查](#常见问题排查)

---

## 前置准备

### 1. 安装 Python 环境

确保系统已安装 Python 3.10 或更高版本：

```bash
python --version
```

### 2. 安装项目依赖

在项目根目录下执行：

```bash
# 创建虚拟环境（如果还没有）
python -m venv venv

# 激活虚拟环境
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（首次使用需要）
playwright install chromium
```

### 3. 配置环境变量（可选）

如果需要使用子AI选题功能，请配置 `.env` 文件：

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件，填入你的 API Key
```

主要配置项：

| 配置项 | 说明 | 示例值 |
|--------|------|--------|
| `CHAT_PROVIDER` | 对话模型供应商（`openrouter` / `fireworks`） | `fireworks` |
| `FIREWORKS_API_KEY` | Fireworks API密钥（当 `CHAT_PROVIDER=fireworks` 时使用） | `fw-xxx` |
| `OPENROUTER_API_KEY` | OpenRouter API密钥（当 `CHAT_PROVIDER=openrouter` 时使用） | `sk-or-xxx` |
| `SUB_MODEL` | 子AI模型 | `accounts/fireworks/models/deepseek-v3p2-thinking` |

---

## 配置 MCP 服务

### 方法一：使用 Cherry Studio 界面配置

1. **打开 Cherry Studio**

2. **进入设置页面**
   - 点击左下角的「设置」图标（齿轮形状）
   - 或使用快捷键 `Ctrl + ,`

3. **找到 MCP 配置**
   - 在设置侧边栏中找到「MCP 服务器」或「Tools」选项
   - 点击「添加服务器」或「Add MCP Server」

4. **填写配置信息**

   | 字段 | 值 |
   |------|-----|
   | **名称** | `exam-paper-assistant` |
   | **命令** | `python` 或虚拟环境的完整路径 |
   | **参数** | MCP服务器脚本的完整路径 |
   | **描述** | 智能组卷辅助系统MCP服务器 |

   **Windows 配置示例：**

   ```
   名称: exam-paper-assistant
   命令: C:\path\to\study_ai\venv\Scripts\python.exe
   参数: C:\path\to\study_ai\backend\mcp\stdio_server.py
   ```

   **或者使用批处理文件：**

   ```
   名称: exam-paper-assistant
   命令: cmd
   参数: /c C:\path\to\study_ai\start.bat mcp
   ```

5. **保存并启用**
   - 点击保存
   - 确保服务开关处于启用状态

---

### 方法二：手动编辑配置文件

Cherry Studio 的 MCP 配置文件通常位于：

- **Windows**: `%APPDATA%\cherry-studio\mcp.json` 或 `%APPDATA%\Cherry Studio\config.json`
- **macOS**: `~/Library/Application Support/cherry-studio/mcp.json`
- **Linux**: `~/.config/cherry-studio/mcp.json`

编辑配置文件，添加以下内容：

```json
{
  "mcpServers": {
    "exam-paper-assistant": {
      "command": "C:\\path\\to\\study_ai\\venv\\Scripts\\python.exe",
      "args": [
        "C:\\path\\to\\study_ai\\backend\\mcp\\stdio_server.py"
      ],
      "description": "智能组卷辅助系统MCP服务器"
    }
  }
}
```

> ⚠️ **注意事项：**
> - Windows 路径使用双反斜杠 `\\` 或单正斜杠 `/`
> - 建议使用虚拟环境的 Python 完整路径，避免依赖冲突
> - 确保路径中没有中文导致的编码问题（本项目路径包含中文用户名，需确保系统编码正确）

---

## 验证服务连接

### 1. 检查服务状态

配置完成后，在 Cherry Studio 中：

1. 查看 MCP 服务列表，确认 `exam-paper-assistant` 显示为「已连接」或绿色状态
2. 如果显示错误，查看错误日志

### 2. 测试工具调用

在对话中输入：

```
列出你可以使用的组卷相关工具
```

如果配置成功，AI 应该能识别到以下工具：

| 工具名称 | 功能描述 |
|----------|----------|
| `search_questions_by_keyword` | 关键词搜索题目 |
| `search_questions_by_knowledge` | 知识点搜索题目 |
| `filter_questions` | 筛选过滤题目 |
| `get_question_info` | 获取题目基本信息 |
| `get_question_details` | 获取题目详细内容 |
| `select_best_question` | 子AI智能选题 |
| `create_paper` | 创建并保存试卷 |

---

## 使用 MCP 工具

### 工具使用流程

```
┌─────────────────┐
│  用户输入需求   │
└────────┬────────┘
         ▼
┌─────────────────┐
│ AI 解析需求     │
└────────┬────────┘
         ▼
┌─────────────────┐
│ 调用搜索工具    │  ← search_questions_by_keyword / knowledge
└────────┬────────┘
         ▼
┌─────────────────┐
│ 筛选题目        │  ← filter_questions
└────────┬────────┘
         ▼
┌─────────────────┐
│ 查看题目详情    │  ← get_question_details（可选）
└────────┬────────┘
         ▼
┌─────────────────┐
│ 智能选题        │  ← select_best_question（可选）
└────────┬────────┘
         ▼
┌─────────────────┐
│ 创建试卷        │  ← create_paper
└────────┬────────┘
         ▼
┌─────────────────┐
│ 返回试卷信息    │
└─────────────────┘
```

### 各工具详细参数

#### 1. search_questions_by_keyword（关键词搜索）

```json
{
  "keyword": "二次函数",        // 必填：搜索关键词
  "subject": "高中数学",        // 可选：学科
  "difficulty": "中等",         // 可选：简单/中等/困难
  "question_type": "选择题",    // 可选：选择题/填空题/解答题
  "limit": 20,                  // 可选：返回数量（默认20）
  "max_pages": 3                // 可选：最多翻页数（默认3）
}
```

#### 2. search_questions_by_knowledge（知识点搜索）

```json
{
  "knowledge_point": "三角函数",  // 必填：知识点名称
  "subject": "高中数学",          // 必填：学科
  "difficulty": "",               // 可选
  "question_type": "",            // 可选
  "limit": 20,
  "max_pages": 3
}
```

#### 3. get_question_details（获取题目详情）

```json
{
  "question_ids": ["12345", "12346", "12347"]  // 最多10个
}
```

#### 4. select_best_question（子AI选题）

```json
{
  "question_ids": ["12345", "12346"],  // 2-5个候选
  "requirement": "需要一道考查函数图像变换的中等难度题目"
}
```

#### 5. create_paper（创建试卷）

```json
{
  "question_ids": ["12345", "12346", "12347"],
  "paper_name": "高二数学周测"
}
```

---

## 常用指令示例

### 基础搜索

```
帮我搜索关于"圆锥曲线"的高中数学题目，要20道
```

```
找一些初中物理"力学"相关的题目，难度简单
```

### 按条件筛选

```
搜索高中化学"氧化还原反应"的选择题，中等难度，要15道
```

```
找高中生物"遗传与进化"的填空题，5道简单的，5道中等的
```

### 完整组卷

```
帮我组一份高一数学单元测试卷：

题目要求：
1. 选择题10道（函数相关，中等难度）
2. 填空题5道（函数图像，简单-中等）
3. 解答题3道（函数应用，中等-困难）

试卷名称：高一数学函数单元测试
```

### 智能选题

```
搜索"导数应用"的题目，然后从中选出最适合考查"函数单调性判断"的3道题
```

### 多知识点组卷

```
我需要一份综合试卷：
- 三角函数：5道选择题
- 数列：3道填空题  
- 导数：2道解答题

每个知识点难度递增，从简单到困难
```

---

## 常见问题排查

### 问题1：MCP 服务无法连接

**症状**：Cherry Studio 显示服务断开或无法启用

**排查步骤**：

1. **检查 Python 路径**
    ```bash
    # 确认虚拟环境的 Python 可执行
    C:\path\to\study_ai\venv\Scripts\python.exe --version
    ```

2. **手动测试 MCP 服务器**
    ```bash
    cd C:\path\to\study_ai
    venv\Scripts\python.exe backend\mcp\stdio_server.py
    ```
   
   如果报错，根据错误信息修复依赖问题。

3. **检查依赖是否完整**
   ```bash
   pip install -r requirements.txt
   ```

### 问题2：工具调用失败

**症状**：AI 调用工具时返回错误

**常见原因**：

| 错误信息 | 解决方案 |
|----------|----------|
| `Playwright not installed` | 运行 `playwright install chromium` |
| `Connection timeout` | 检查网络连接，确认组卷网可访问 |
| `Database error` | 运行 `python database/models.py` 初始化数据库 |

### 问题3：路径包含中文导致问题

**症状**：配置文件无法正确解析

**解决方案**：

1. 确保配置文件使用 UTF-8 编码保存
2. 或将项目移动到纯英文路径下

### 问题4：爬虫获取数据失败

**症状**：搜索返回空结果或报错

**排查步骤**：

1. 检查网络是否能访问 `zujuan.com`
2. 可能是网站反爬限制，等待一段时间重试
3. 如果网站改版，可能需要更新爬虫代码

---

## 进阶配置

### 配置子AI模型

编辑 `.env` 文件：

```bash
# 使用更智能的模型进行选题
SUB_MODEL=anthropic/claude-3-haiku
SUB_MODEL_TEMPERATURE=0.3
SUB_MODEL_MAX_TOKENS=1000
```

### 调整爬虫参数

如需修改默认学科，编辑 `.env`：

```bash
DEFAULT_SUBJECT=高中物理
```

---

## 技术支持

- 查看 `docs/TROUBLESHOOTING.md` 获取更多故障排除信息
- 查看 `docs/API.md` 了解完整 API 接口
- 项目数据库位于 `./.local/exam_papers.db`（兼容旧路径：`exam_papers.db`）

---

## SVG 公式解析功能

本项目支持将组卷网的 SVG 数学公式自动转换为 LaTeX 格式，便于 AI 理解和处理数学表达式。

### 工作原理

1. **字形签名匹配** - 非 OCR 方案，通过计算 SVG path 数据的 MD5 哈希来识别字符
2. **结构识别** - 自动识别分数、根号、上下标等数学结构
3. **签名库** - 已收录 60+ 常用数学符号签名

### 支持的数学结构

| 结构 | LaTeX 输出示例 |
|------|----------------|
| 分数 | `\frac{1}{2}` |
| 根号 | `\sqrt{x^{2}+4}` |
| 上标 | `x^{2}` |
| 下标 | `a_{n}` |
| 大型运算符 | `\sum_{i=1}^{n}` |
| 嵌套结构 | `\sqrt{\frac{1}{x^{2}+4}}` |

### 使用方式

当 AI 获取题目详情时（`get_question_details` 工具），公式会自动以 LaTeX 格式呈现，方便 AI 理解数学内容。

### 扩展签名库

如果遇到未识别的字符，可使用调试工具：

```bash
cd utils
python debug_formula.py <formula_hash>
```

然后根据提示添加新签名到 `glyph_signatures.json`。

---

## 附录：支持的学科列表

| 学段 | 支持学科 |
|------|----------|
| 高中 | 数学、语文、英语、物理、化学、生物、政治、历史、地理 |
| 初中 | 数学、语文、英语、物理、化学、生物、道德与法治、历史、地理 |
| 小学 | 数学、语文、英语 |

---

*最后更新：2025-12-06*
