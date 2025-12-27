import asyncio
from pathlib import Path
import sys

import httpx

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from utils.svg_to_latex import load_signatures, svg_content_to_latex

async def main():
    urls = [
        # 8c7e4bb8
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/77162983bac5421ae447d8fedd391fdc.svg",
        # a0d48578
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/f99bcbd5a9e1b3f0e6d54ae44b18fd28.svg",
        # f54db794
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/9e6ad7f03ad1c0f2eb7816dedecb7e82.svg",
        # b922bd09
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/5bb118697645d39c93fddc4234af1635.svg",
        # b27d3ae3
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/2b853eaed1b4d91371810f607dda5dd4.svg"
    ]
    
    load_signatures()
    
    async with httpx.AsyncClient() as client:
        for url in urls:
            print(f"\nURL: {url}")
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    latex, unknown = svg_content_to_latex(resp.text)
                    print(f"Latex: {latex}")
                    print(f"Unknown: {unknown}")
            except Exception as e:
                print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
