# SVG 转 LaTeX 解析改进计划

## 改进完成状态

| 问题 | 状态 | 完成日期 | 说明 |
|------|------|----------|------|
| D签名问题（上下文感知识别） | ✅ 已完成 | 2025-12-05 | 添加模糊签名映射和上下文解析函数 |
| 根号解析 | ✅ 已完成 | 2025-12-05 | 添加 SqrtRegion 数据结构和检测函数 |
| 复杂分数结构（嵌套结构） | ✅ 已完成 | 2025-12-05 | 支持根号下有分数等递归结构 |

---

## 已实现功能详情

### 1. 上下文感知识别 ✅

**问题描述**：
- 某些签名在不同上下文中可能表示不同字符（如 D 可能是减号）

**实现方案**：
1. 添加 `AMBIGUOUS_SIGNATURES` 模糊签名映射表
2. 添加 `is_operand_char()` 判断操作数字符
3. 添加 `resolve_ambiguous_char()` 上下文解析函数
4. 在 `glyphs_to_latex()` 中使用上下文感知解析

**代码位置**：`utils/svg_to_latex.py`

**使用方法**：
```python
# 添加模糊签名到映射表
AMBIGUOUS_SIGNATURES["c36b3f1d"] = {
    "default": "D",
    "operator_context": "-",
}
```

---

### 2. 根号解析 ✅

**问题描述**：
- 需要正确识别根号符号并格式化为 `\sqrt{}`
- 根号下的内容需要被正确包裹

**实现方案**：
1. 添加 `SqrtRegion` 数据类表示根号区域
2. 添加 `is_sqrt_signature()` 判断根号签名
3. 添加 `detect_sqrt_regions()` 检测根号区域
4. 更新 `parse_svg_glyphs()` 返回所有线段信息
5. 在 `glyphs_to_latex_advanced()` 中处理根号结构

**代码位置**：`utils/svg_to_latex.py`

**检测方法**：
- 方法1：通过根号符号签名 (`\sqrt`) 检测
- 方法2：通过线段组合检测（斜线+水平线的组合）

---

### 3. 复杂嵌套结构 ✅

**问题描述**：
- 根号下有分数等嵌套结构时解析不正确
- 例如：$\sqrt{\frac{a}{b}}$ 需要正确嵌套

**实现方案**：
1. 在 `glyphs_to_latex_advanced()` 中使用递归处理
2. 先处理根号区域，检测其内部是否有分数
3. 如果有分数，递归调用 `glyphs_to_latex_advanced()`
4. 分离已处理的根号内分数线，避免重复处理

**代码位置**：`utils/svg_to_latex.py` - `glyphs_to_latex_advanced` 函数

---

## API 变更

### `parse_svg_glyphs()` 返回值变更

**旧版本**：
```python
def parse_svg_glyphs(svg_content: str) -> Tuple[List[Glyph], List[FractionBar]]:
    ...
    return unique_glyphs, fraction_bars
```

**新版本**：
```python
def parse_svg_glyphs(svg_content: str) -> Tuple[List[Glyph], List[FractionBar], List[Tuple[float, float, float, float]]]:
    ...
    return unique_glyphs, fraction_bars, all_lines
```

### `glyphs_to_latex_advanced()` 参数变更

**旧版本**：
```python
def glyphs_to_latex_advanced(glyphs: List[Glyph], fraction_bars: List[FractionBar] = None):
```

**新版本**：
```python
def glyphs_to_latex_advanced(
    glyphs: List[Glyph], 
    fraction_bars: List[FractionBar] = None,
    svg_lines: List[Tuple[float, float, float, float]] = None
):
```

---

## 测试结果

```
╔════════════════════════════════════════════════════════════╗
║               SVG → LaTeX 转换功能测试                      ║
╚════════════════════════════════════════════════════════════╝

  ✓ 通过 - 签名加载
  ✓ 通过 - SVG 解析
  ✓ 通过 - 签名计算
  ✓ 通过 - LaTeX 转换
  ✓ 通过 - httpx 可用性

总计: 5/5 测试通过

🎉 所有测试都通过了！
```

---

## 后续可能的改进

1. **更精确的根号范围检测**：目前基于线段位置估算，可以考虑使用更复杂的几何分析

2. **更多嵌套结构**：支持多层嵌套（如分数中的根号中的分数）

3. **性能优化**：对于复杂SVG，考虑缓存解析结果

4. **可视化调试**：添加调试模式输出解析过程的可视化表示
