"""
调试公式签名的工具
用法: python debug_formula.py <formula_hash或完整URL>
"""
import asyncio
import sys
import httpx
from svg_to_latex import parse_svg_glyphs, load_signatures, GLYPH_SIGNATURES, add_signature


async def debug_formula(formula_input: str):
    """分析公式中的所有字形签名"""
    load_signatures()

    # 处理输入
    if formula_input.startswith('http'):
        svg_url = formula_input
        if svg_url.endswith('.png'):
            svg_url = svg_url.replace('.png', '.svg')
    else:
        svg_url = f'https://staticzujuan.xkw.com/quesimg/Upload/formula/{formula_input}.svg'

    png_url = svg_url.replace('.svg', '.png')

    print(f"分析公式: {svg_url}")
    print(f"PNG预览: {png_url}")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(svg_url)
        if resp.status_code != 200:
            print(f"获取SVG失败: {resp.status_code}")
            return
        svg = resp.text

    glyphs, fraction_bars, svg_lines = parse_svg_glyphs(svg)

    print(f"\n发现 {len(glyphs)} 个字形, {len(fraction_bars)} 条分数线, {len(svg_lines)} 条线段")
    print("\n字形详情 (按x坐标排序):")
    print("-" * 70)

    unknown_count = 0
    for i, g in enumerate(sorted(glyphs, key=lambda x: (x.y, x.x))):
        status = "  " if g.char else "??"
        char_display = g.char if g.char else f"[未知:{g.signature}]"
        print(f"{status} [{i+1:2d}] sig={g.signature}  char={char_display:10s}  "
              f"pos=({g.x:6.1f}, {g.y:6.1f})  size=({g.width:5.1f} x {g.height:5.1f})")
        if not g.char:
            unknown_count += 1

    if fraction_bars:
        print(f"\n分数线:")
        for bar in fraction_bars:
            print(f"  x1={bar.x1:.1f}, x2={bar.x2:.1f}, y={bar.y:.1f}")

    print("\n" + "=" * 70)

    if unknown_count > 0:
        print(f"\n有 {unknown_count} 个未知签名需要添加到签名库")
        print("使用以下命令添加签名:")
        for g in glyphs:
            if not g.char:
                print(f'  add_signature("{g.signature}", "字符")')
    else:
        print("\n所有字形都已识别!")


async def interactive_add():
    """交互式添加签名"""
    print("\n交互式签名添加")
    print("-" * 40)

    while True:
        sig = input("输入签名 (或 'q' 退出): ").strip()
        if sig.lower() == 'q':
            break

        char = input(f"签名 {sig} 对应的字符: ").strip()
        if char:
            add_signature(sig, char)
            print(f"已添加: {sig} -> {char}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python debug_formula.py <formula_hash或URL>")
        print("示例: python debug_formula.py dad2a36927223bd70f426ba06aea4b45")
        sys.exit(1)

    asyncio.run(debug_formula(sys.argv[1]))
