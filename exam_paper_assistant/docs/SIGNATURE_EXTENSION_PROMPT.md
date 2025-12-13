# SVG签名扩展任务提示词

将以下内容复制给AI，让其继续扩展签名库：

---

## 任务：扩展SVG公式转LaTeX的签名映射表

### 背景

本项目使用**字形签名匹配法**将组卷网(zujuan.xkw.com)的SVG数学公式转换为LaTeX。核心原理：

1. SVG中每个字符是一个`<path>`元素
2. 对path的`d`属性计算MD5，取前8位作为签名
3. 通过预定义的签名→LaTeX映射表进行转换

**优势**：精确匹配，无OCR误差，速度快

### 当前状态

- 签名映射文件：`utils/glyph_signatures.json`
- 转换工具：`utils/svg_to_latex.py`
- 已有签名：约162个（数字、字母、常见运算符、几何符号）
- 问题：仍有部分字符未收录，转换时显示`[?签名]`

### 你的任务

1. **收集新签名**：运行收集命令获取未知签名
2. **分析字形**：通过生成的HTML页面识别字形对应的LaTeX
3. **添加映射**：将新签名添加到映射表
4. **验证测试**：确保转换正确

### 工作流程

#### 步骤1：收集签名

```bash
cd exam_paper_assistant/utils
python svg_to_latex.py --collect -q 29811335 29811336 29811337 29811338 29811339 29811340
```

这会生成`signature_analyzer.html`，包含所有收集到的字形。

#### 步骤2：分析单个SVG

对于特定的未知签名，可以获取SVG并分析：

```python
import urllib.request
import hashlib
import re

svg_url = "https://staticzujuan.xkw.com/quesimg/Upload/formula/[公式ID].svg"
with urllib.request.urlopen(svg_url) as resp:
    svg = resp.read().decode('utf-8')

# 提取所有字形
pattern = r'<g[^>]*transform="translate\(([^,)]+),?\s*([^)]*)\)"[^>]*>.*?<path[^>]*d="([^"]+)"'
matches = re.findall(pattern, svg, re.DOTALL)

for x, y, path_d in sorted(matches, key=lambda m: float(m[0])):
    sig = hashlib.md5(path_d.encode()).hexdigest()[:8]
    print(f"x={float(x):>7.2f}, sig={sig}")
```

#### 步骤3：添加新签名

```python
# 方法1：命令行添加
python svg_to_latex.py --add-sig "a1b2c3d4" "\\alpha"

# 方法2：直接编辑 glyph_signatures.json
{
  "a1b2c3d4": "\\alpha",
  "b2c3d4e5": "\\beta"
}

# 方法3：Python API
from svg_to_latex import add_signature, add_signatures_batch
add_signature("a1b2c3d4", "\\alpha")
```

#### 步骤4：验证

```bash
python svg_to_latex.py --test
python svg_to_latex.py -u "https://staticzujuan.xkw.com/quesimg/Upload/formula/[测试公式].svg"
```

### 签名映射规范

| 类型 | LaTeX格式 | 示例 |
|------|-----------|------|
| 数字 | 直接字符 | `0`, `1`, `2` |
| 小写字母 | 直接字符 | `a`, `b`, `x` |
| 大写字母 | 直接字符 | `A`, `B`, `P` |
| 希腊字母 | `\\命令` | `\\alpha`, `\\beta`, `\\pi`, `\\theta` |
| 运算符 | `\\命令`或直接 | `+`, `-`, `=`, `\\times`, `\\div`, `\\pm` |
| 关系符 | `\\命令` | `\\leq`, `\\geq`, `\\neq`, `\\approx` |
| 括号 | 直接或`\\` | `(`, `)`, `\\{`, `\\}` |
| 特殊符号 | `\\命令` | `\\infty`, `\\partial`, `\\sum`, `\\int` |

### 常见字形参考

```
数字: 0123456789
小写: abcdefghijklmnopqrstuvwxyz
大写: ABCDEFGHIJKLMNOPQRSTUVWXYZ
希腊: α(\\alpha) β(\\beta) γ(\\gamma) δ(\\delta) θ(\\theta) λ(\\lambda) μ(\\mu) π(\\pi) σ(\\sigma) φ(\\phi) ω(\\omega)
运算: + - = × ÷ ± ∓ ·
关系: < > ≤ ≥ ≠ ≈ ≡ ∼
括号: ( ) [ ] { } |
箭头: → ← ⇒ ⇐ ↔
其他: ∞ ∂ ∇ ∑ ∏ ∫ √
```

### 注意事项

1. **签名格式**：必须是8位小写十六进制（MD5前8位）
2. **LaTeX转义**：JSON中反斜杠需要双写，如`"\\alpha"`
3. **避免混淆**：
   - `l`(小写L) vs `I`(大写i) vs `1`(数字)
   - `0`(数字) vs `O`(大写o)
   - `-`(减号) vs `−`(负号)
   - `x`(变量) vs `×`(乘号，用`\\times`)
4. **验证必须**：每次添加后运行测试确认

### 当前未知签名示例

运行以下命令查看当前缺失的签名：

```bash
python -c "
from svg_to_latex import quick_svg_to_latex
latex, unknown = quick_svg_to_latex('https://staticzujuan.xkw.com/quesimg/Upload/formula/7c3a9b723303acf1669d4d88a7172b99.svg')
print(f'LaTeX: {latex}')
print(f'未知签名: {unknown}')
"
```

### 文件位置

```
exam_paper_assistant/
├── utils/
│   ├── svg_to_latex.py          # 主工具（勿修改核心逻辑）
│   ├── glyph_signatures.json    # 签名映射（需要扩展）
│   └── signature_analyzer.html  # 可视化分析（自动生成）
└── docs/
    └── SVG_TO_LATEX.md          # 详细文档
```

### 预期成果

1. 扩展`glyph_signatures.json`，新增20-50个签名
2. 覆盖常见数学符号（希腊字母、运算符、关系符）
3. 所有新签名通过验证测试
4. 更新文档中的签名统计

---

**开始工作时，请先运行`--collect`命令收集签名，然后逐个分析和添加映射。**
