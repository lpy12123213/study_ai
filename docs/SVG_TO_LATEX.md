# SVG 与 LaTeX 导出

Study AI 在题目解析、示意图生成、自学资料和试卷导出中会遇到 SVG、公式图片和 LaTeX 之间的转换问题。本文说明当前能力、边界、工具链和排查方式。

## 使用场景

- 题源中的 SVG 公式需要转成可读 LaTeX。
- 自学资料生成了 SVG 示意图，需要在 Markdown 或导出文件中引用。
- 试卷或资料导出到 LaTeX / PDF / DOCX 时，图片和公式需要可编译。
- LaTeX 编译失败时，需要定位是公式、图形还是工具链问题。

## 相关模块

- `backend/core/svg_utils/svg_to_latex.py`
- `backend/core/svg_utils/glyph_signatures.json`
- `backend/core/svg_utils/unknown_signatures.py`
- `backend/core/svg_diagram.py`
- `backend/api/media.py`
- `backend/api/study_materials.py`
- `backend/agent/tools/generation/latex_export.py`
- `backend/agent/tools/generation/latex_export_convert.py`
- `backend/agent/tools/generation/latex_export_refine.py`
- `backend/agent/tools/generation/latex_export_compile.py`
- `backend/paper_compose/export.py`

## 当前能力

- 本地生成媒体通过 `/api/media/generated/{filename}` 访问。
- 远程媒体可通过 `/api/media/proxy?url=...` 缓存，但远程 SVG 默认被拒绝。
- SVG 公式转换依赖字形签名和结构识别，适合稳定来源的数学公式。
- LaTeX 导出会尽量返回可编辑 `.tex`，PDF 编译依赖本机 LaTeX 工具链。

## 工具链要求

PDF 导出常见依赖：

- `xelatex` 或 `pdflatex`
- `dvisvgm`

图形回退：

- `asy`

DOCX：

- `pandoc`

排查：

```bash
xelatex --version
dvisvgm --version
asy --version
pandoc --version
```

## 安全边界

媒体代理默认限制：

- 只接受图片 content type。
- 拒绝远程 SVG。
- 限制文件大小和缓存数量。
- 域名可通过 allowlist 控制。

这样做是为了避免把远程 SVG 中的脚本、外链或异常内容代理到前端。

## 常见问题

### PDF 编译失败

处理：

- 先导出 LaTeX，查看 `.tex`。
- 检查日志中第一个报错位置。
- 确认公式块、环境、花括号是否闭合。
- 增加 `PAPER_EXPORT_LATEX_TIMEOUT_S`。

### SVG 公式识别不完整

处理：

- 查看是否出现未知签名。
- 仅对稳定来源扩展 `glyph_signatures.json`。
- 不要用猜测替代无法识别的数学符号。

### DOCX 图片缺失

处理：

- 确认图片 URL 是本地可访问的 `/api/media/generated/...`。
- 确认 Pandoc 能访问对应文件。
- 对外部远程图，优先先缓存为本地生成媒体。

## 建议工作流

1. 先生成 Markdown。
2. 检查公式和图片是否在 Web UI 中正常显示。
3. 转换为 LaTeX。
4. 检查 `.tex`。
5. 编译 PDF 或导出 DOCX。
6. 如果编译失败，保留 `.tex` 和日志作为排查输入。

## 相关文档

- `CONFIGURATION.md`：导出相关环境变量。
- `DEPLOYMENT.md`：外部工具链要求。
- `TROUBLESHOOTING.md`：PDF、DOCX 和媒体排查。
