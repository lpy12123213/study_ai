"""
签名分析工具 - 生成HTML页面用于可视化识别字形
"""
import urllib.request
import hashlib
import re
import subprocess
from collections import defaultdict
import json
import os

# 已知签名
KNOWN_SIGNATURES = {
    "ee8570c5": "P",
    "2aa7df06": "o",
    "d7198a8e": "O",
    "b9716cb9": "2",
    "5f32a7e2": "4",
    "e113c1a7": "+",
    "a1040187": "=",
    "8c6104df": ":",
    "cf58f988": "x",
    "6cb4ef65": "y",
}


def extract_glyph_svg(full_svg: str, path_d: str) -> str:
    """从完整SVG中提取单个字形的SVG"""
    # 创建只包含单个字形的SVG
    svg_template = '''<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50" viewBox="-5 -15 30 30">
  <path d="{path}" fill="black" stroke="none"/>
</svg>'''
    return svg_template.format(path=path_d)


def collect_signatures(question_ids: list) -> dict:
    """收集签名数据"""
    all_sigs = defaultdict(lambda: {'count': 0, 'paths': [], 'examples': []})

    for qid in question_ids:
        url = f'https://zujuan.xkw.com/11q{qid}.html'
        try:
            result = subprocess.run(['curl', '-s', url], capture_output=True, timeout=30)
            html = result.stdout.decode('utf-8', errors='ignore')

            urls = list(set(re.findall(r'https://[^"]+/formula/([^"]+)\.png', html)))

            for formula_id in urls[:30]:
                svg_url = f'https://staticzujuan.xkw.com/quesimg/Upload/formula/{formula_id}.svg'
                try:
                    with urllib.request.urlopen(svg_url, timeout=5) as resp:
                        svg = resp.read().decode('utf-8')

                    pattern = r'<path d="([^"]+)"'
                    paths = re.findall(pattern, svg)

                    for p in paths:
                        sig = hashlib.md5(p.encode()).hexdigest()[:8]
                        all_sigs[sig]['count'] += 1
                        if not all_sigs[sig]['paths']:
                            all_sigs[sig]['paths'].append(p)
                        if len(all_sigs[sig]['examples']) < 3:
                            all_sigs[sig]['examples'].append(formula_id[:16])
                except:
                    pass
        except:
            pass

    return dict(all_sigs)


def generate_html(signatures: dict, output_path: str):
    """生成可视化HTML页面"""
    html = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>签名分析器</title>
    <style>
        body { font-family: Arial, sans-serif; padding: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; }
        .card { border: 1px solid #ccc; padding: 15px; border-radius: 8px; }
        .card.known { background: #e8f5e9; }
        .card.unknown { background: #fff3e0; }
        .glyph { width: 50px; height: 50px; margin: 10px auto; display: block; }
        .sig { font-family: monospace; font-size: 12px; color: #666; }
        .count { color: #1976d2; font-weight: bold; }
        .char { font-size: 24px; color: #388e3c; }
        input { width: 60px; font-size: 18px; text-align: center; }
        button { margin-top: 10px; padding: 5px 15px; cursor: pointer; }
        #export { margin: 20px 0; padding: 10px 20px; font-size: 16px; background: #1976d2; color: white; border: none; cursor: pointer; }
    </style>
</head>
<body>
    <h1>字形签名分析器</h1>
    <p>在输入框中填写对应的LaTeX字符，然后点击导出</p>
    <button id="export" onclick="exportData()">导出签名映射</button>
    <div class="grid">
'''

    # 按出现次数排序
    sorted_sigs = sorted(signatures.items(), key=lambda x: -x[1]['count'])

    for sig, data in sorted_sigs:
        if data['count'] < 2:
            continue

        known = KNOWN_SIGNATURES.get(sig, "")
        card_class = "known" if known else "unknown"

        # 生成内嵌SVG
        path_d = data['paths'][0] if data['paths'] else ""
        svg_content = f'''<svg class="glyph" xmlns="http://www.w3.org/2000/svg" viewBox="-2 -12 15 15">
            <path d="{path_d}" fill="black" stroke="none" transform="scale(1,-1)"/>
        </svg>''' if path_d else ""

        html += f'''
        <div class="card {card_class}" data-sig="{sig}">
            {svg_content}
            <div class="sig">{sig}</div>
            <div class="count">出现 {data['count']} 次</div>
            <div>
                <input type="text" class="char-input" value="{known}" placeholder="?">
            </div>
        </div>
'''

    html += '''
    </div>
    <script>
        function exportData() {
            const cards = document.querySelectorAll('.card');
            const mapping = {};
            cards.forEach(card => {
                const sig = card.dataset.sig;
                const char = card.querySelector('.char-input').value.trim();
                if (char) {
                    mapping[sig] = char;
                }
            });

            const json = JSON.stringify(mapping, null, 2);
            console.log(json);

            // 下载文件
            const blob = new Blob([json], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'glyph_signatures.json';
            a.click();
        }
    </script>
</body>
</html>
'''

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"已生成: {output_path}")


def main():
    print("收集签名数据...")
    question_ids = [str(29811335 + i) for i in range(10)]
    signatures = collect_signatures(question_ids)

    print(f"共收集 {len(signatures)} 个签名")

    output_path = os.path.join(os.path.dirname(__file__), 'signature_analyzer.html')
    generate_html(signatures, output_path)

    # 也输出统计信息
    print("\n高频签名:")
    for sig, data in sorted(signatures.items(), key=lambda x: -x[1]['count'])[:20]:
        known = KNOWN_SIGNATURES.get(sig, "?")
        print(f"  {sig}: {data['count']:>3}次 -> {known}")


if __name__ == "__main__":
    main()
