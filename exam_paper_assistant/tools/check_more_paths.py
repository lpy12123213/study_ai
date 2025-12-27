import hashlib
import re
import httpx
import asyncio

async def main():
    sigs = ['bbc076b0', '9f4df464', '7a285146', 'ac9aeff0', '0c725770', 'c5232a6d', '1183a0ed', '51bf7efb', '2959a3ea', 'f8c4dd7e']
    urls = [
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/75433100c06cd370783cf0935d3bb97b.svg",
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/ab1ec9e85ace524fdafe1a9e5eeab650.svg",
        "https://staticzujuan.xkw.com/quesimg/Upload/formula/c2d1cc87f3494fd57a58524e45645260.svg"
    ]
    
    async with httpx.AsyncClient() as client:
        for url in urls:
            print(f"\nURL: {url}")
            resp = await client.get(url)
            if resp.status_code != 200: continue
            svg = resp.text
            paths = re.findall(r'<path[^>]*d="([^"]+)"', svg)
            for p in paths:
                h = hashlib.md5(p.encode()).hexdigest()[:8]
                if h in sigs:
                    print(f"  Match {h}: {p[:50]}...")

if __name__ == "__main__":
    asyncio.run(main())

