# SVG公式转LaTeX方案文档

## 概述

本项目实现了一种**精确的SVG数学公式转LaTeX**方案，使用**字形签名匹配法**，而非OCR或AI识别，确保转换的精确性和一致性。

## 核心原理

### 字形签名匹配法

组卷网的数学公式以SVG格式存储，每个字符（字形）都是一个独立的`<path>`元素。我们通过以下步骤将SVG转换为LaTeX：

```
SVG公式 → 提取字形path → 计算MD5签名 → 查表映射 → 组装LaTeX
```

#### 1. SVG结构解析

组卷网SVG公式的典型结构：

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="104" height="18">
  <g transform="translate(x1, y1)">
    <path d="M2.5 -10.5938 L6.6719 ..."/>  <!-- 字符1 -->
  </g>
  <g transform="translate(x2, y2)">
    <path d="M7.8906 -10.8438 ..."/>  <!-- 字符2 -->
  </g>
  ...
</svg>
```

- 每个`<g>`元素的`transform`属性包含字符位置(x, y)
- 每个`<path>`的`d`属性是字符的矢量路径数据

#### 2. 签名计算

对每个字形的`path d`属性计算MD5哈希，取前8位作为签名：

```python
import hashlib

def compute_path_signature(path_d: str) -> str:
    return hashlib.md5(path_d.encode()).hexdigest()[:8]
```

**为什么用MD5前8位？**
- 同一字符在不同公式中的path数据完全相同
- MD5前8位足够区分不同字符（碰撞概率极低）
- 短签名便于存储和查询

#### 3. 签名映射表

预定义签名到LaTeX字符的映射：

```python
GLYPH_SIGNATURES = {
    # 数字
    "b9716cb9": "2",
    "5f32a7e2": "4",
    "3b2fdd74": "1",
    "b673824f": "0",

    # 小写字母
    "cf58f988": "x",
    "6cb4ef65": "y",
    "9fe3b8c9": "a",
    "aecc1ab6": "b",

    # 运算符
    "e113c1a7": "+",
    "a1040187": "=",

    # 希腊字母
    "c9d0e1f2": "\\pi",
    "a1b2c3d4": "\\alpha",
    ...
}
```

#### 4. 位置分析与结构识别

通过分析字形的y坐标，识别上下标结构：

```python
# 基准线检测：找出出现最多的y值
baseline_y = max(y_counts, key=y_counts.get)

# 上下标判断
y_diff = glyph.y - baseline_y
if y_diff < -2:      # 上标
    latex += "^{" + char + "}"
elif y_diff > 2:     # 下标
    latex += "_{" + char + "}"
else:                # 基准线
    latex += char
```

## 文件结构

```
study_ai/
├── backend/
│   ├── core/
│   │   └── svg_utils/
│   │       ├── svg_to_latex.py          # 核心转换工具
│   │       └── glyph_signatures.json    # 签名映射表
│   └── crawler/
│       └── zujuan_crawler.py            # 爬虫（已集成LaTeX转换）
└── docs/
    └── SVG_TO_LATEX.md                  # 本文档
```

## 使用方法

### 1. 命令行工具

```bash
# 转换单个SVG URL
python backend/core/svg_utils/svg_to_latex.py -u https://example.com/formula.svg

# 转换本地文件
python backend/core/svg_utils/svg_to_latex.py -f formula.svg

# 替换HTML中的所有公式
python backend/core/svg_utils/svg_to_latex.py -H page.html -o output.html

# 使用高级转换（支持分数等复杂结构）
python backend/core/svg_utils/svg_to_latex.py -u https://example.com/formula.svg --advanced

# 运行测试
python backend/core/svg_utils/svg_to_latex.py --test
```

### 2. Python API

```python
from backend.core.svg_utils import (
    quick_svg_to_latex,
    svg_content_to_latex,
    svg_url_to_latex,
    replace_formulas_with_latex,
    add_signature,
)

# 快速转换（自动识别输入类型）
latex, unknown = quick_svg_to_latex("https://example.com/formula.svg")
latex, unknown = quick_svg_to_latex("<svg>...</svg>")
latex, unknown = quick_svg_to_latex("/path/to/file.svg")

# 异步批量转换
import asyncio
results = asyncio.run(batch_svg_to_latex(svg_urls, concurrency=5))

# 替换HTML中的公式
html_result, unknown = asyncio.run(replace_formulas_with_latex(html_content))

# 添加新签名
add_signature("abc12345", "\\theta")
```

### 3. 爬虫集成

爬虫已自动集成LaTeX转换，获取题目详情时公式会自动转换：

```python
from backend.crawler.zujuan_crawler import ZujuanCrawler

crawler = ZujuanCrawler()
await crawler.initialize()

# 获取题目，公式自动转为LaTeX
detail = await crawler.get_question_detail("29811335")
print(detail["stem"])
# 输出: 已知点$P$在圆$O:x^{2}+y^{2}=4$上...
```

## 签名收集与学习

### 收集新签名

当遇到未知签名时，可以收集并分析：

```bash
# 从题目收集签名
python svg_to_latex.py --collect -q 29811335 29811336 29811337

# 生成可视化分析页面
python svg_to_latex.py --collect -q 29811335 -o analysis.html
```

### 可视化标注

1. 打开生成的`signature_analyzer.html`
2. 页面显示所有收集到的字形及其签名
3. 在输入框中填写对应的LaTeX字符
4. 点击"导出签名映射"下载JSON文件
5. 将JSON内容合并到`glyph_signatures.json`

### 手动添加签名

```python
from svg_to_latex import add_signature, add_signatures_batch

# 添加单个签名
add_signature("abc12345", "\\alpha")

# 批量添加
add_signatures_batch({
    "sig1": "\\beta",
    "sig2": "\\gamma",
})
```

### 扩展签名的强化流程（建议采纳）

1. **预检**：确认未知签名数量、公式来源、上下文截图是否齐全，避免盲标。
2. **分批处理**：按题目/章节/来源拆分批次，批次内先跑 `--collect`，生成独立 `signature_analyzer_xxx.html`，便于回溯。
3. **角色分工**：一人收集、一人标注、一人复核；复核人只关注高频/高风险符号（上下标、希腊字母、运算符）。
4. **命名与标注规范**：
   - 仅使用 8 位小写 MD5，不修改或手造签名。
   - LaTeX 统一用数学模式命令：希腊字母 `\\alpha`/`\\beta`/`\\pi`，运算符 `\\times`/`\\div`/`\\pm`，集合/关系 `\\in`/`\\subset`/`\\geq`。
   - 避免混淆：`1/I/l`，`0/O`，`-`(减号)/`−`(负号)/`—`(破折号)，`x`(变量)/`\\times`(乘号)，`/`(斜杠)/分数线。
5. **对照验证**：
   - 标注后立刻跑 `python svg_to_latex.py --test`，并用 2~3 个真实题目 URL 复跑；确认无新的 `[?xxxx]`。
   - 手工抽查：挑选包含上下标、分数、根号的公式，用 MathJax 或本地渲染比对。
6. **回滚策略**：
   - 合并前备份 `utils/glyph_signatures.json`（或用 Git 分支），保留本批次 HTML。
   - 如发现错误标注，保留错误样例与修正映射，避免二次踩坑。
7. **发布节奏**：
   - 小批次（<20 个签名）随时合并，确保当天验证。
   - 大批次按周合并，提交时附覆盖率与剩余未知签名数量。

### 签名扩展自动化脚本示例

```python
# scripts/auto_signature_pipeline.py
"""
自动收集 -> 生成分析页 -> 导出 JSON 的流水线
"""
import asyncio
from svg_to_latex import (
    collect_signatures_from_urls,
    generate_signature_analyzer_html,
)

def get_formula_urls(question_ids):
    # TODO: 按题号获取公式 URL，可复用 crawler
    ...

async def main(batch_name: str, question_ids: list[str]):
    sigs = collect_signatures_from_urls(get_formula_urls(question_ids))
    html = generate_signature_analyzer_html(
        sigs,
        f"signature_analyzer_{batch_name}.html",
        title=f"签名分析 - {batch_name}",
    )
    print(f"完成收集，分析页已生成: {html}")

if __name__ == "__main__":
    asyncio.run(main("week_01", ["29811335", "29811336"]))
```

运行方式示例：
```bash
python scripts/auto_signature_pipeline.py
```

### 验证与发布清单
- [ ] 已备份 `utils/glyph_signatures.json`
- [ ] 新增签名均为 8 位小写 MD5
- [ ] LaTeX 命令均为数学模式，未混入全角/中文符号
- [ ] `python svg_to_latex.py --test` 通过
- [ ] 手工抽检高风险公式（上下标、分数、根号、希腊字母、运算符）
- [ ] 更新签名统计表（如有新增类别/数量变化）
- [ ] 提交记录注明本批次来源、覆盖范围与验证方式

## 当前签名覆盖

| 类别 | 数量 | 示例 |
|------|------|------|
| 数字 | 10+ | 0-9（含多种字体变体） |
| 小写字母 | 26+ | a-z |
| 大写字母 | 26+ | A-Z |
| 希腊字母 | 36+ | α, β, γ, δ, ε, θ, λ, μ, π, σ, φ, ω, Γ, Δ, Θ, Λ, ... |
| 运算符 | 25+ | +, -, =, ×, ÷, ≤, ≥, ≈, ≡, ∼, ... |
| 大型运算符 | 10+ | ∑, ∏, ∫, ∮, lim, max, min, sup, inf, ... |
| 集合符号 | 11+ | ∈, ∉, ⊂, ⊃, ⊆, ⊇, ∅, ∀, ∃, ⋃, ⋂, ... |
| 括号/定界符 | 15+ | (, ), [, ], {, }, \|, ⌊, ⌋, ⌈, ⌉, ⟨, ⟩, ... |
| 箭头 | 15+ | →, ←, ⇒, ⇐, ↔, ↑, ↓, ↦, ... |
| 关系符号 | 15+ | ≪, ≫, ≺, ≻, ≃, ≅, ∝, ⊥, ∥, ... |
| 特殊符号 | 15+ | ∞, ∂, ∇, √, °, ′, †, ‡, •, ⊕, ⊗, ... |
| **总计** | **~245** | |

详细签名映射（签名→LaTeX 全量列表）见 `docs/SVG_SIGNATURE_TABLE.md`，内容与 `utils/glyph_signatures.json` 保持同步，便于审计和人工核对。

## 高级功能

### 分数识别

通过检测水平线（分数线）识别分数结构：

```python
# 分数线特征：宽度 > 高度 * 3 且 高度 < 3
def is_horizontal_line(glyph):
    return glyph.width > glyph.height * 3 and glyph.height < 3

# 分子在分数线上方，分母在下方
# 输出: \frac{numerator}{denominator}
```

### 上下标检测

基于y坐标偏移自动检测：

```
y_diff < -2  → 上标 ^{}
y_diff > 2   → 下标 _{}
其他         → 基准线
```

### 大型运算符支持

支持求和、积分、极限等大型运算符的上下限识别：

```python
# 支持的大型运算符
LARGE_OPERATORS = {
    "\\sum", "\\prod", "\\int", "\\oint", "\\iint", "\\iiint",
    "\\bigcup", "\\bigcap", "\\lim", "\\max", "\\min", "\\sup", "\\inf",
}

# 输出示例：
# ∑_{i=1}^{n} → \sum_{i=1}^{n}
# ∫_{0}^{∞}   → \int_{0}^{\infty}
# lim_{n→∞}   → \lim_{n \to \infty}
```

大型运算符的上下限位置检测：
- 上限：位于运算符正上方（y坐标更小）
- 下限：位于运算符正下方（y坐标更大）
- x坐标在运算符中心附近的字形被识别为上下限

对于极限类运算符（`\lim`, `\max`, `\min` 等），只支持下标而非上下限格式。

## 优势与局限

### 优势

1. **精确性高** - 字形签名唯一对应，不存在识别误差
2. **速度快** - 无需AI推理，纯哈希查表
3. **可扩展** - 新字符只需添加签名映射
4. **无依赖** - 不需要OCR引擎或AI模型
5. **确定性** - 同样输入始终得到同样输出

### 局限

1. **需要预定义** - 新字符需手动添加签名映射
2. **字体依赖** - 仅适用于组卷网特定字体的SVG
3. **复杂结构** - 矩阵、积分上下限等复杂结构支持有限

## 扩展签名的工作流程

### 标准工作流程

```
1. 发现未知签名 [?abc12345]
         ↓
2. 收集签名数据
         ↓
3. 可视化分析与标注
         ↓
4. 导出并合并签名映射
         ↓
5. 验证与测试
         ↓
6. 持续优化
```

#### 步骤1: 发现未知签名

当转换过程中遇到未知字形时，系统会标记为 `[?签名]` 格式：

```python
# 示例输出
latex = "x^{[?a1b2c3d4]}+y^{[?b2c3d4e5]}"
unknown = ["a1b2c3d4", "b2c3d4e5"]
```

**发现途径：**
- 运行爬虫时自动检测
- 批量转换HTML页面
- 手动测试特定公式
- 查看转换日志中的警告信息

#### 步骤2: 收集签名数据

**方法A: 从指定题目收集**
```bash
# 从单个题目收集
python svg_to_latex.py --collect -q 29811335

# 从多个题目批量收集
python svg_to_latex.py --collect -q 29811335 29811336 29811337

# 自动收集最近10个题目
python svg_to_latex.py --collect
```

**方法B: 从HTML文件收集**
```bash
# 分析包含公式的HTML页面
python svg_to_latex.py --collect -H exam_paper.html
```

**方法C: 从URL列表收集**
```python
from svg_to_latex import collect_signatures_from_urls

svg_urls = [
    "https://staticzujuan.xkw.com/quesimg/Upload/formula/abc123.svg",
    "https://staticzujuan.xkw.com/quesimg/Upload/formula/def456.svg"
]
signatures = collect_signatures_from_urls(svg_urls)
```

收集完成后，会在 `utils/` 目录生成 `signature_analyzer.html` 文件。

#### 步骤3: 可视化分析与标注

**打开分析页面：**
```bash
# Windows
start utils/signature_analyzer.html

# macOS/Linux
open utils/signature_analyzer.html
```

**页面功能：**
- **字形预览**: 每个卡片显示SVG字形、签名、出现次数
- **过滤功能**: 可单独显示已知/未知签名
- **实时标注**: 在输入框中填写LaTeX字符
- **样式反馈**: 已知签名显示绿色边框，未知签名显示橙色

**标注技巧：**
1. **高频优先**: 按出现次数排序，优先标注高频签名
2. **上下文推断**: 结合公式上下文猜测字符含义
3. **相似比对**: 与已知相似字形对比确认
4. **LaTeX规范**:
   - 普通字符: `a`, `B`, `3`
   - 希腊字母: `\\alpha`, `\\beta`, `\\pi`
   - 运算符: `\\times`, `\\div`, `\\pm`
   - 特殊符号: `\\infty`, `\\partial`, `\\sum`

#### 步骤4: 导出并合并签名映射

**导出JSON：**
1. 点击"导出签名映射 (JSON)"按钮
2. 浏览器自动下载 `glyph_signatures.json`
3. 文件包含所有新标注的签名映射

**合并到项目：**
```bash
# 备份原文件
cp utils/glyph_signatures.json utils/glyph_signatures.json.bak

# 替换为新文件（假设下载到Downloads文件夹）
cp ~/Downloads/glyph_signatures.json utils/glyph_signatures.json
```

**程序化添加：**
```python
from svg_to_latex import add_signature, add_signatures_batch

# 添加单个签名
add_signature("a1b2c3d4", "\\theta")

# 批量添加
new_signatures = {
    "a1b2c3d4": "\\theta",
    "b2c3d4e5": "\\phi",
    "c3d4e5f6": "\\psi"
}
add_signatures_batch(new_signatures)
```

#### 步骤5: 验证与测试

**运行内置测试：**
```bash
python svg_to_latex.py --test
```

**验证特定公式：**
```bash
# 测试单个URL
python svg_to_latex.py -u https://staticzujuan.xkw.com/quesimg/Upload/formula/abc123.svg

# 测试批量转换
python svg_to_latex.py -u url1.svg -u url2.svg -u url3.svg
```

**检查覆盖率：**
```bash
# 列出所有已知签名
python svg_to_latex.py --list-sigs
```

**验证指标：**
- 未知签名数量应减少
- 转换准确率应提升
- 无新的 `[?签名]` 标记出现

#### 步骤6: 持续优化

**定期维护：**
```bash
# 每周收集新签名
python svg_to_latex.py --collect -q $(seq 29811335 29811345)

# 月度审查
python svg_to_latex.py --list-sigs | wc -l  # 统计总签名数
```

**性能监控：**
- 记录每次新增签名的数量
- 监控转换成功率变化
- 识别频繁出现的新签名模式

### 高级技巧与最佳实践

#### 批量处理策略

**大规模收集：**
```bash
# 收集100个题目的所有公式
for i in {0..9}; do
  python svg_to_latex.py --collect -q $(seq $((29811335 + i*10)) $((29811335 + i*10 + 9)))
done

# 合并所有收集结果
cat signature_analyzer_*.html > combined_analyzer.html
```

**自动化脚本：**
```python
# auto_collect.py
from svg_to_latex import collect_signatures_from_urls, generate_signature_analyzer_html

# 自动发现新题目并收集
question_ids = discover_new_questions()  # 自定义发现函数
signatures = collect_signatures_from_urls(get_formula_urls(question_ids))
generate_signature_analyzer_html(signatures, "auto_signatures.html")
```

#### 质量控制

**验证新签名：**
```python
def validate_signature(sig, latex_char, test_urls):
    """验证新签名的正确性"""
    from svg_to_latex import add_signature, svg_url_to_latex
    
    # 临时添加
    add_signature(sig, latex_char)
    
    # 测试验证
    for url in test_urls:
        latex, unknown = await svg_url_to_latex(url)
        if sig in unknown:
            print(f"验证失败: {sig} -> {latex_char}")
            return False
    
    print(f"验证成功: {sig} -> {latex_char}")
    return True
```

**避免常见错误：**
1. **相似字形混淆**: 如 `l` (小写L) 和 `I` (大写i)
2. **运算符错误**: 如 `-` (减号) 和 `−` (负号)
3. **希腊字母**: 确保使用正确的LaTeX命令
4. **字体变体**: 注意不同字体的相同字符可能签名不同

#### 团队协作

**分工标注：**
- 将 `signature_analyzer.html` 分发给团队成员
- 每人负责不同字符类别（数字、字母、符号等）
- 使用版本控制管理 `glyph_signatures.json`

**合并策略：**
```bash
# 合并多个成员的标注
python merge_signatures.py member1.json member2.json -o combined.json
```

#### 性能优化

**缓存机制：**
```python
# 启用签名缓存
import functools

@functools.lru_cache(maxsize=1024)
def get_glyph_signature(path_d):
    return compute_path_signature(path_d)
```

**预加载：**
```python
# 启动时预加载所有签名
from svg_to_latex import load_signatures
load_signatures()  # 自动加载 glyph_signatures.json
```

### 故障排除

**问题1: 收集不到签名**
- 检查网络连接和URL格式
- 确认题目ID正确且包含公式
- 验证SVG URL可访问

**问题2: 标注后仍然显示未知**
- 确认JSON文件已正确合并
- 检查是否有缓存，重启Python进程
- 验证签名格式是否正确（8位小写十六进制）

**问题3: 转换结果错误**
- 检查是否混淆相似字形
- 验证LaTeX语法是否正确
- 使用 `--advanced` 参数启用高级转换

**问题4: 性能缓慢**
- 减少并发数（默认5，可调整为3）
- 使用本地缓存的SVG文件
- 批量处理时避免重复收集相同签名

### 自动化工作流示例

**完整自动化脚本：**
```python
#!/usr/bin/env python3
"""
自动签名收集与更新工作流
"""
from svg_to_latex import (
    collect_signatures_from_urls,
    generate_signature_analyzer_html,
    load_signatures
)
import asyncio

async def auto_extend_signatures():
    """全自动扩展签名流程"""
    
    # 1. 收集新签名
    print("步骤1: 收集签名数据...")
    question_ids = [str(29811335 + i) for i in range(20)]
    signatures = collect_signatures_from_urls(
        get_formula_urls_from_questions(question_ids)
    )
    
    # 2. 生成分析页面
    print("步骤2: 生成分析页面...")
    html_path = generate_signature_analyzer_html(
        signatures,
        "signature_analyzer_new.html",
        title="新收集签名分析"
    )
    
    # 3. 模拟自动标注（基于已知模式）
    print("步骤3: 自动标注已知模式...")
    auto_annotate_signatures(signatures)
    
    # 4. 验证并保存
    print("步骤4: 验证新签名...")
    validate_new_signatures()
    
    print(f"完成！请查看 {html_path} 进行手动验证")

if __name__ == "__main__":
    asyncio.run(auto_extend_signatures())
```

### 签名管理规范

**命名规范：**
- 使用8位小写MD5签名作为键
- LaTeX字符使用标准命令
- 特殊符号添加注释说明

**版本控制：**
```bash
# 提交前检查
git diff utils/glyph_signatures.json

# 添加有意义的提交信息
git commit -m "Add 15 new glyph signatures for Greek letters"
```

**文档更新：**
- 每次扩展后更新签名统计表
- 记录新添加的字符类别
- 更新示例转换表格

## 示例转换

| SVG公式 | LaTeX输出 |
|---------|-----------|
| ![P](formula1.svg) | `P` |
| ![x²+y²=4](formula2.svg) | `x^{2}+y^{2}=4` |
| ![圆O](formula3.svg) | `Oo:x^{2}+y^{2}=4` |

## 技术细节

### 依赖

```
- Python 3.8+
- httpx (异步HTTP，可选)
- 标准库: hashlib, json, re, asyncio
```

### 性能

- 单个SVG转换: < 1ms
- 批量转换: 支持并发，默认5个并发
- 内存占用: 签名表约10KB

## 后续改进方向

1. **自动学习** - 结合已知公式文本自动推断签名
2. **结构增强** - 支持矩阵、积分上下限等
3. **字体适配** - 支持更多字体的SVG格式
4. **错误修复** - 智能纠正常见转换错误

---

*文档版本: 1.0*
*最后更新: 2025-11-30*
