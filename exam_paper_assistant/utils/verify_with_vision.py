"""
使用视觉模型验证SVG签名识别的准确性

用法:
  python verify_with_vision.py --api-key YOUR_OPENROUTER_API_KEY
  python verify_with_vision.py --api-key YOUR_KEY --model qwen/qwen3-235b-a22b
"""
import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

# OpenRouter配置（可被命令行参数覆盖）
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


async def recognize_formula_with_vision(image_url: str, api_key: str, model: str) -> str:
    """使用视觉模型识别公式"""
    if not api_key:
        return "[ERROR: No API key]"

    async with httpx.AsyncClient(timeout=120) as client:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "请识别这个数学公式图片，只输出LaTeX格式的公式内容，不要任何解释和思考过程。例如输入圆的方程图片，输出：x^{2}+y^{2}=4"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url
                            }
                        }
                    ]
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1,
        }

        try:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
            )

            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                # 提取纯LaTeX部分（去除思考过程）
                if "```" in content:
                    # 提取代码块内容
                    import re
                    match = re.search(r'```(?:latex)?\s*(.*?)\s*```', content, re.DOTALL)
                    if match:
                        content = match.group(1).strip()
                # 去除可能的$符号
                content = content.strip('$').strip()
                return content
            else:
                return f"[ERROR: {resp.status_code} - {resp.text[:200]}]"
        except Exception as e:
            return f"[ERROR: {e}]"


async def verify_with_vision(api_key: str, model: str):
    """使用视觉模型验证签名识别结果"""
    from svg_to_latex import svg_url_to_latex

    # 测试公式列表
    formula_ids = [
        'dad2a36927223bd70f426ba06aea4b45',  # 简单：P
        '7c3a9b723303acf1669d4d88a7172b99',  # 复杂：圆方程
        'afeccf0358c02b53554a0f6d3dc33cbd',  # 字母数字
        '0d736deaaf629851b7d63fd43dbafcb5',
        '98803fa6c14b5620ef75940dfa7038ca',
        '200f3cedabbbd093be9f0fa209474af6',  # 包含≤
    ]

    print("=" * 70)
    print("视觉模型验证 - 对比签名识别 vs AI识别")
    print(f"视觉模型: {model}")
    print("=" * 70)

    if not api_key:
        print("\n[错误] 未配置 API Key")
        print("请使用 --api-key 参数或设置 OPENROUTER_API_KEY 环境变量")
        return

    results = []

    for i, fid in enumerate(formula_ids):
        svg_url = f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{fid}.svg"
        png_url = f"https://staticzujuan.xkw.com/quesimg/Upload/formula/{fid}.png"

        print(f"\n[{i+1}/{len(formula_ids)}] 公式: {fid[:16]}...")

        # 签名识别
        sig_result, unknown = await svg_url_to_latex(svg_url)
        print(f"  签名识别: {sig_result}")
        if unknown:
            print(f"  未知签名: {unknown}")

        # 视觉模型识别
        print(f"  正在调用视觉模型...")
        vision_result = await recognize_formula_with_vision(png_url, api_key, model)
        print(f"  视觉识别: {vision_result}")

        # 简单对比（去除空格和特殊字符）
        def normalize(s):
            if not s:
                return ""
            s = s.replace(" ", "").replace("$", "")
            s = s.replace("\\\\", "\\")
            s = s.replace("\\leq", "≤").replace("\\geq", "≥")
            s = s.replace("\\times", "×").replace("\\cdot", "·")
            return s.lower()

        sig_clean = normalize(sig_result)
        vis_clean = normalize(vision_result)

        match = "[OK]" if sig_clean == vis_clean else "[??]"
        print(f"  对比结果: {match}")

        results.append({
            "formula_id": fid,
            "signature": sig_result,
            "vision": vision_result,
            "sig_normalized": sig_clean,
            "vis_normalized": vis_clean,
            "match": match == "[OK]"
        })

        # 避免请求过快
        await asyncio.sleep(2)

    # 统计
    print("\n" + "=" * 70)
    print("验证结果统计")
    print("=" * 70)

    matched = sum(1 for r in results if r["match"])
    total = len(results)

    print(f"完全匹配: {matched}/{total} ({100*matched/total:.0f}%)")

    # 显示不匹配的
    mismatches = [r for r in results if not r["match"]]
    if mismatches:
        print("\n不匹配项（需要检查）:")
        for r in mismatches:
            print(f"  公式: {r['formula_id'][:16]}...")
            print(f"    签名识别: {r['signature']}")
            print(f"    视觉识别: {r['vision']}")
            print(f"    标准化签名: {r['sig_normalized']}")
            print(f"    标准化视觉: {r['vis_normalized']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用视觉模型验证SVG签名识别")
    parser.add_argument("--api-key", default=os.getenv("OPENROUTER_API_KEY", ""),
                        help="OpenRouter API Key")
    parser.add_argument("--model", default="qwen/qwen3-235b-a22b",
                        help="视觉模型名称 (默认: qwen/qwen3-235b-a22b)")
    args = parser.parse_args()

    asyncio.run(verify_with_vision(args.api_key, args.model))
