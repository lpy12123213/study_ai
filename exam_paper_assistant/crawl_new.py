"""直接获取题目页面的公式"""
import asyncio
import sys
sys.path.insert(0, '.')

async def main():
    from crawler.zujuan_crawler import ZujuanCrawler
    import urllib.request
    import hashlib
    import re
    import json
    
    # 加载现有签名
    with open('utils/glyph_signatures.json', 'r', encoding='utf-8') as f:
        known = json.load(f)
        known_sigs = {k: v for k, v in known.items() if len(k) == 8 and all(c in '0123456789abcdef' for c in k)}
    
    print(f'已加载 {len(known_sigs)} 个真实签名')
    
    # 初始化爬虫获取cookie
    crawler = ZujuanCrawler()
    await crawler.initialize()
    cookies = crawler.cookies
    
    # 搜索题目
    print('\n搜索数学题目...')
    result = await crawler.search_by_keyword('导数', limit=30)
    
    questions = result.get('questions', [])
    print(f'找到 {len(questions)} 个题目')
    
    await crawler.close()
    
    # 直接访问题目页面获取公式
    all_formula_ids = set()
    
    for q in questions[:15]:
        qid = q['question_id']
        url = f'https://zujuan.xkw.com/11q{qid}.html'
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Cookie': cookies
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                html = resp.read().decode('utf-8', errors='ignore')
            fids = set(re.findall(r'/formula/([0-9a-f]{32})\.png', html))
            all_formula_ids.update(fids)
            if fids:
                print(f'  题目 {qid}: {len(fids)} 个公式')
        except Exception as e:
            print(f'  题目 {qid}: 失败')
    
    print(f'\n共收集 {len(all_formula_ids)} 个公式ID')
    
    if not all_formula_ids:
        print('未找到公式，尝试直接测试一些公式URL...')
        # 尝试一些可能存在的公式
        test_prefixes = ['a', 'b', 'c', 'd', 'e', 'f', '0', '1', '2', '3']
        for p in test_prefixes:
            test_id = p * 32
            url = f'https://staticzujuan.xkw.com/quesimg/Upload/formula/{test_id}.svg'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        all_formula_ids.add(test_id)
                        print(f'  找到: {test_id[:8]}...')
            except:
                pass
    
    # 获取SVG签名
    def get_svg_sigs(fid):
        url = f'https://staticzujuan.xkw.com/quesimg/Upload/formula/{fid}.svg'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                svg = resp.read().decode('utf-8')
            pattern = r'<g[^>]*transform="translate\([^)]+\)"[^>]*>.*?<path[^>]*d="([^"]+)"'
            return [(hashlib.md5(p.encode()).hexdigest()[:8], p[:350]) for p in re.findall(pattern, svg, re.DOTALL)]
        except:
            return []
    
    unknown = {}
    known_count = 0
    
    for fid in all_formula_ids:
        for sig, path in get_svg_sigs(fid):
            if sig in known_sigs:
                known_count += 1
            elif sig not in unknown:
                unknown[sig] = path
                print(f'新签名: {sig}')
    
    print(f'\n已识别: {known_count} 次')
    print(f'新签名: {len(unknown)} 个')
    
    if unknown:
        html = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><title>新签名</title>
<style>body{font-family:Arial;padding:20px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px}
.card{border:2px solid #f90;padding:8px;border-radius:6px;background:#fff;text-align:center}
.g{width:50px;height:50px;margin:5px auto;border:1px solid #ddd}.s{font:11px monospace;color:#666}
input{width:45px;font-size:13px;text-align:center;padding:2px}</style></head>
<body><h2>新签名 (''' + str(len(unknown)) + ''')</h2><div class="grid">'''
        
        for sig, path in unknown.items():
            html += f'<div class="card"><svg class="g" viewBox="-5 -15 25 25"><path d="{path[:400]}" fill="black" transform="scale(0.8,-0.8)"/></svg><div class="s">{sig}</div><input id="{sig}" placeholder="?"></div>'
        
        html += '</div><br><button onclick="exp()">导出</button><pre id="o"></pre><script>function exp(){const s=' + json.dumps(list(unknown.keys())) + ';const m={};s.forEach(x=>{const v=document.getElementById(x).value.trim();if(v)m[x]=v});document.getElementById("o").textContent=JSON.stringify(m,null,2)}</script></body></html>'
        
        with open('new_sigs.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print(f'\n已生成 new_sigs.html，签名列表:')
        for s in list(unknown.keys()):
            print(f'  {s}')

if __name__ == '__main__':
    asyncio.run(main())
