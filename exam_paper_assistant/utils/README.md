# SVG公式签名映射表扩展指南

## 📋 概述

本项目使用字形签名（MD5前8位）精确匹配法将组卷网SVG公式转换为LaTeX，而非OCR或AI识别。通过扩展签名映射表，可以提高公式识别的准确度。

## 🎯 工作流程

### 方法一：快速启动（推荐）

#### 1️⃣ 收集签名

```bash
# 从指定题目收集签名
cd utils
python quick_start.py collect 29811335 29811336 29811337

# 或使用扩展工具
python signature_extender.py collect -q 29811335 29811336 -o analyzer.html
```

这会：
- 下载指定题目的所有公式
- 提取每个字形的MD5签名
- 生成 `signature_analyzer.html` 文件

#### 2️⃣ 识别字符

在浏览器中打开生成的HTML文件：
- 查看左侧的字形图像
- 在右侧输入框填写对应的LaTeX字符

**关键规则：**
- `\alpha` - 希腊字母用反斜杠前缀
- `\times` - 运算符用反斜杠前缀
- `+` - 简单符号直接输入
- `(` - 括号直接输入

#### 3️⃣ 导出映射

在HTML页面中：
- 点击 "📥 导出为JSON" 按钮
- 保存为 `glyph_signatures_new.json`

#### 4️⃣ 合并映射

```bash
# 方法1：使用快速脚本
python signature_extender.py merge glyph_signatures_new.json

# 方法2：直接添加映射
python quick_start.py add a1b2c3d4 "\\alpha"

# 方法3：手动编辑
# 打开 utils/glyph_signatures.json
# 添加新的签名映射，格式为:
# "签名": "LaTeX字符"
```

#### 5️⃣ 验证结果

```bash
# 列出所有映射
python quick_start.py list

# 列出包含"alpha"的映射
python quick_start.py list alpha

# 测试转换
python svg_to_latex.py --test
```

---

### 方法二：使用扩展工具（完整功能）

#### 基本命令

```bash
# 列出现有映射
python signature_extender.py list

# 添加单个映射
python signature_extender.py add a1b2c3d4 "\\alpha"

# 收集签名
python signature_extender.py collect -q 29811335 29811336 -o output.html

# 合并JSON文件
python signature_extender.py merge other_sigs.json

# 导出映射
python signature_extender.py export backup.json
```

---

## 🔧 高级用法

### 从代码调用

```python
from signature_extender import SignatureMapper, SignatureCollector

# 创建映射管理器
mapper = SignatureMapper()

# 添加单个映射
mapper.add("a1b2c3d4", "\\alpha")

# 批量添加
mappings = {
    "a1b2c3d4": "\\alpha",
    "b2c3d4e5": "\\beta",
}
mapper.add_batch(mappings)

# 保存
mapper.save()

# 合并另一个JSON
mapper.merge("other_signatures.json")
```

### 收集签名的高级配置

```python
from signature_extender import SignatureCollector

collector = SignatureCollector(timeout=15)

# 从单个SVG URL收集
collector.collect_from_url("https://example.com/formula.svg", source_id="qid123")

# 从多个题目收集
stats = collector.collect_from_questions(
    ["29811335", "29811336"],
    max_formulas_per_q=50  # 每题最多收集50个公式
)

# 获取统计信息
info = collector.get_statistics()
print(f"总签名数: {info['total_signatures']}")
print(f"总出现次: {info['total_occurrences']}")

# 获取未知签名
unknown = collector.get_unknown_signatures(mapper)
for sig, info in unknown[:10]:
    print(f"{sig}: {info.count}次")

# 导出HTML进行标注
collector.export_html("analyzer.html", mapper)
```

---

## 📝 签名映射规范

### 签名格式
- **8位小写十六进制字符串** - MD5的前8位
- 示例：`a1b2c3d4`, `cf58f988`, `e113c1a7`

### LaTeX字符格式

| 类型 | 示例 | 说明 |
|------|------|------|
| 数字 | `0`, `1`, `2` | 直接输入数字 |
| 小写字母 | `x`, `y`, `z` | 直接输入字母 |
| 大写字母 | `A`, `B`, `Z` | 直接输入字母 |
| 希腊字母 | `\alpha`, `\beta` | 反斜杠 + 英文名称 |
| 运算符 | `+`, `=`, `-` | 直接输入符号 |
| 特殊运算符 | `\times`, `\div`, `\pm` | 反斜杠前缀 |
| 括号 | `(`, `)`, `[`, `]` | 直接输入括号 |
| 特殊括号 | `\{`, `\}`, `\|` | 反斜杠转义 |
| 数学函数 | `\sin`, `\cos`, `\log` | 反斜杠前缀 |
| 箭头 | `\rightarrow`, `\leftarrow` | 反斜杠前缀 |
| 其他 | `\infty`, `\partial`, `\sqrt` | 反斜杠前缀 |

### JSON格式示例

```json
{
  "b9716cb9": "2",
  "cf58f988": "x",
  "a1b2c3d4": "\\alpha",
  "e113c1a7": "+",
  "b3c4d5e6": "\\times",
  "c6d7e8f9": "("
}
```

⚠️ **注意**：在JSON中，反斜杠必须转义为 `\\`

---

## 🐛 故障排除

### 问题1：下载速度慢或超时

```python
# 增加超时时间
collector = SignatureCollector(timeout=30)
```

### 问题2：某些题目获取失败

- 可能是网络问题，重试即可
- 某些题目可能需要登录，跳过它们

### 问题3：生成的字形显示不正确

- 可能是SVG viewBox设置问题
- 在HTML中编辑 `viewBox` 属性

### 问题4：合并JSON时冲突

```python
# 查看冲突详情
new_count, conflict_count = mapper.merge("other_sigs.json")
print(f"冲突数: {conflict_count}")
```

---

## 📊 监控进度

### 获取当前识别率

```python
from signature_extender import SignatureMapper

mapper = SignatureMapper()
print(f"已加载签名数: {len(mapper.signatures)}")
```

### 查找高频未识别字符

```python
from signature_extender import SignatureCollector

collector = SignatureCollector()
collector.collect_from_questions(["29811335", "29811336"])

unknown = collector.get_unknown_signatures(mapper)
print(f"未识别签名数: {len(unknown)}")

# 显示最高频的未识别字符
for sig, info in unknown[:20]:
    print(f"{sig}: {info.count}次")
```

---

## 🎨 HTML分析器功能

生成的 `signature_analyzer.html` 提供：

- **字形可视化** - 查看SVG中的字形外观
- **统计信息** - 识别率、已知/未知签名数
- **快速过滤** - 显示/隐藏已知或未知签名
- **批量编辑** - 一次性编辑多个字形的LaTeX映射
- **一键导出** - 生成标准JSON格式的映射
- **批量复制** - 快速复制未识别签名列表

---

## 🚀 完整工作流示例

```bash
# 1. 进入utils目录
cd utils

# 2. 从10个题目收集签名
python quick_start.py collect 29811335 29811336 29811337 29811338 29811339 29811340 29811341 29811342 29811343 29811344

# 3. 打开生成的 signature_analyzer.html 进行标注
# （使用浏览器打开，填写LaTeX字符）

# 4. 导出新映射为 glyph_signatures_new.json

# 5. 合并新映射
python signature_extender.py merge glyph_signatures_new.json

# 6. 验证
python svg_to_latex.py --test

# 7. 查看更新后的统计
python quick_start.py list
```

---

## 📈 性能优化

### 批量收集提示

- 每个题目可收集30-50个公式
- 每次收集建议选择10-20个题目
- 可以多次收集并合并结果

### 签名映射优化

- 优先映射高频未识别字符
- 关注数字、基本运算符和希腊字母
- 特殊符号和函数名称可以后续添加

---

## 🔄 持续维护

建议定期：

1. **收集新签名** - 从新的题目收集签名
2. **分析未识别字符** - 找出高频未识别的字形
3. **批量标注** - 通过HTML分析器批量添加映射
4. **合并更新** - 定期合并新映射
5. **测试验证** - 运行测试确保准确性

---

## 📚 相关文件

```
utils/
├── glyph_signatures.json      # 签名映射表（主文件）
├── svg_to_latex.py            # 核心转换工具
├── signature_extender.py       # 扩展工具类库
├── quick_start.py             # 快速启动脚本
├── signature_analyzer.html    # HTML分析器（生成的）
└── README.md                  # 本文档
```

---

## ❓ 常见问题

**Q: 如何确保映射的准确性？**
A: 通过视觉识别字形图像，对比已有的PDF/LaTeX文档。高频字符应该优先验证。

**Q: 可以导入第三方的签名映射吗？**
A: 可以，使用 `merge` 命令合并任何标准JSON格式的映射文件。

**Q: 签名会发生变化吗？**
A: 同一字形的SVG path不变，签名也不会变。但不同的SVG库可能生成不同的path。

**Q: 如何添加新的希腊字母？**
A: 使用格式 `\greekletter_name`，例如 `\rho`, `\tau`, `\upsilon`

---

更新日期: 2025年11月30日
