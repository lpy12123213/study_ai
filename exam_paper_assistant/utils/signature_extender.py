"""
签名映射表扩展工具
支持从HTML页面收集签名、可视化分析、批量导入等功能
"""
import json
import os
import re
import asyncio
import urllib.request
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, asdict


@dataclass
class SignatureInfo:
    """签名信息数据结构"""
    signature: str
    character: Optional[str] = None
    count: int = 0
    paths: List[str] = None
    sources: List[str] = None  # 来源题目ID列表

    def __post_init__(self):
        if self.paths is None:
            self.paths = []
        if self.sources is None:
            self.sources = []


class SignatureMapper:
    """签名映射管理器"""

    def __init__(self, json_path: Optional[str] = None):
        """初始化映射器"""
        if json_path is None:
            json_path = os.path.join(os.path.dirname(__file__), "glyph_signatures.json")
        self.json_path = json_path
        self.signatures: Dict[str, str] = {}
        self.load()

    def load(self):
        """从JSON文件加载映射"""
        if os.path.exists(self.json_path):
            try:
                with open(self.json_path, 'r', encoding='utf-8') as f:
                    self.signatures = json.load(f)
                print(f"✓ 已加载 {len(self.signatures)} 个签名映射")
            except Exception as e:
                print(f"✗ 加载失败: {e}")
        else:
            print(f"⚠ 文件不存在，将创建新文件: {self.json_path}")
            self.signatures = {}

    def save(self):
        """保存映射到JSON文件"""
        try:
            with open(self.json_path, 'w', encoding='utf-8') as f:
                json.dump(self.signatures, f, ensure_ascii=False, indent=2, sort_keys=True)
            print(f"✓ 已保存 {len(self.signatures)} 个签名映射到 {self.json_path}")
            return True
        except Exception as e:
            print(f"✗ 保存失败: {e}")
            return False

    def add(self, signature: str, character: str, auto_save: bool = True) -> bool:
        """添加单个签名映射"""
        if not isinstance(signature, str) or len(signature) != 8:
            print(f"✗ 签名格式错误: {signature}（应为8位字符串）")
            return False

        if signature in self.signatures:
            old = self.signatures[signature]
            print(f"⚠ 签名 {signature} 已存在，旧值: {old}")

        self.signatures[signature] = character
        print(f"✓ 已添加: {signature} -> {character}")

        if auto_save:
            return self.save()
        return True

    def add_batch(self, mappings: Dict[str, str], auto_save: bool = True) -> Tuple[int, int]:
        """批量添加签名映射

        Returns:
            (新增数量, 更新数量)
        """
        new_count = 0
        update_count = 0

        for sig, char in mappings.items():
            if sig in self.signatures:
                if self.signatures[sig] != char:
                    update_count += 1
            else:
                new_count += 1
            self.signatures[sig] = char

        print(f"✓ 批量添加完成: {new_count} 个新增, {update_count} 个更新")

        if auto_save:
            self.save()
        return new_count, update_count

    def remove(self, signature: str, auto_save: bool = True) -> bool:
        """移除签名映射"""
        if signature not in self.signatures:
            print(f"✗ 签名不存在: {signature}")
            return False

        char = self.signatures.pop(signature)
        print(f"✓ 已移除: {signature} ({char})")

        if auto_save:
            self.save()
        return True

    def list_all(self, filter_char: Optional[str] = None):
        """列出所有映射"""
        items = self.signatures.items()
        if filter_char:
            items = [(k, v) for k, v in items if filter_char.lower() in v.lower()]

        for sig, char in sorted(items):
            print(f"  {sig}: {char}")

        print(f"\n总计: {len(self.signatures)} 个签名映射")

    def export(self, output_path: str) -> bool:
        """导出为JSON文件"""
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(self.signatures, f, ensure_ascii=False, indent=2, sort_keys=True)
            print(f"✓ 已导出到: {output_path}")
            return True
        except Exception as e:
            print(f"✗ 导出失败: {e}")
            return False

    def merge(self, other_json_path: str) -> Tuple[int, int]:
        """合并另一个JSON文件的映射

        Returns:
            (新增数量, 冲突数量)
        """
        try:
            with open(other_json_path, 'r', encoding='utf-8') as f:
                other = json.load(f)
        except Exception as e:
            print(f"✗ 加载文件失败: {e}")
            return 0, 0

        new_count = 0
        conflict_count = 0

        for sig, char in other.items():
            if sig in self.signatures:
                if self.signatures[sig] != char:
                    conflict_count += 1
                    print(f"⚠ 冲突: {sig}: {self.signatures[sig]} vs {char}")
            else:
                new_count += 1
            self.signatures[sig] = char

        print(f"✓ 合并完成: {new_count} 个新增, {conflict_count} 个冲突")
        self.save()
        return new_count, conflict_count


class SignatureCollector:
    """签名收集器"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.collected: Dict[str, SignatureInfo] = defaultdict(
            lambda: SignatureInfo(signature="", count=0, paths=[], sources=[])
        )

    def collect_from_svg(self, svg_content: str, source_id: str = ""):
        """从SVG内容收集签名"""
        # 提取所有path元素
        paths = re.findall(r'<path[^>]*d="([^"]+)"', svg_content)

        for path_d in paths:
            sig = hashlib.md5(path_d.encode()).hexdigest()[:8]
            self.collected[sig].signature = sig
            self.collected[sig].count += 1

            if len(self.collected[sig].paths) < 3:
                self.collected[sig].paths.append(path_d)

            if source_id and source_id not in self.collected[sig].sources:
                self.collected[sig].sources.append(source_id)

    def collect_from_url(self, svg_url: str, source_id: str = "") -> bool:
        """从URL下载并收集签名"""
        try:
            with urllib.request.urlopen(svg_url, timeout=self.timeout) as resp:
                svg = resp.read().decode('utf-8')
            self.collect_from_svg(svg, source_id)
            return True
        except Exception as e:
            print(f"✗ 下载失败: {svg_url} - {e}")
            return False

    def collect_from_questions(self, question_ids: List[str], max_formulas_per_q: int = 50) -> Dict[str, int]:
        """从组卷网题目收集签名

        Returns:
            {question_id: collected_count}
        """
        stats = {}

        for qid in question_ids:
            url = f'https://zujuan.xkw.com/11q{qid}.html'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                html = urllib.request.urlopen(req, timeout=self.timeout).read().decode('utf-8', errors='ignore')

                # 提取公式PNG URL
                formula_ids = list(set(re.findall(
                    r'https://[^"]+/formula/([^"]+)\.png', html
                )))[:max_formulas_per_q]

                count = 0
                for f_id in formula_ids:
                    svg_url = f'https://staticzujuan.xkw.com/quesimg/Upload/formula/{f_id}.svg'
                    if self.collect_from_url(svg_url, qid):
                        count += 1

                stats[qid] = count
                print(f"✓ 题目 {qid}: 收集 {count} 个公式")
            except Exception as e:
                print(f"✗ 题目 {qid}: 获取失败 - {e}")
                stats[qid] = 0

        return stats

    def get_unknown_signatures(self, mapper: SignatureMapper) -> List[Tuple[str, SignatureInfo]]:
        """获取未映射的签名

        Returns:
            按出现次数排序的 (signature, info) 列表
        """
        unknown = [
            (sig, info) for sig, info in self.collected.items()
            if sig not in mapper.signatures
        ]
        return sorted(unknown, key=lambda x: -x[1].count)

    def get_statistics(self) -> Dict:
        """获取收集统计信息"""
        return {
            "total_signatures": len(self.collected),
            "total_occurrences": sum(info.count for info in self.collected.values()),
            "total_sources": len(set(s for info in self.collected.values() for s in info.sources)),
        }

    def export_html(self, output_path: str, mapper: SignatureMapper = None, title: str = "字形签名分析器"):
        """生成可视化HTML页面"""
        sorted_sigs = sorted(self.collected.items(), key=lambda x: -x[1].count)
        known_sigs = mapper.signatures if mapper else {}

        html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ font-family: "Segoe UI", Tahoma, sans-serif; padding: 20px; background: #f0f2f5; }}
        h1 {{ color: #1976d2; margin-bottom: 10px; }}
        .summary {{ background: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .stat-item {{ display: inline-block; margin-right: 30px; }}
        .stat-label {{ color: #666; font-size: 14px; }}
        .stat-value {{ font-size: 24px; font-weight: bold; color: #1976d2; }}
        .controls {{ background: white; padding: 15px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .filter-group {{ display: inline-block; margin-right: 20px; }}
        .filter-group label {{ margin-right: 10px; }}
        button {{ padding: 10px 20px; background: #1976d2; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
        button:hover {{ background: #1565c0; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }}
        .card {{ background: white; border-radius: 8px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); transition: all 0.3s; }}
        .card:hover {{ box-shadow: 0 4px 8px rgba(0,0,0,0.15); }}
        .card.unknown {{ border-left: 4px solid #ff9800; }}
        .card.known {{ border-left: 4px solid #4caf50; }}
        .glyph {{ width: 60px; height: 60px; margin: 0 auto 10px; display: flex; align-items: center; justify-content: center; background: #f5f5f5; border-radius: 4px; font-size: 30px; overflow: hidden; }}
        .sig {{ font-family: "Courier New", monospace; font-size: 12px; color: #666; word-break: break-all; margin: 5px 0; }}
        .count {{ color: #1976d2; font-weight: bold; }}
        .current-char {{ font-size: 18px; color: #388e3c; font-weight: bold; margin: 5px 0; }}
        .sources {{ font-size: 11px; color: #999; }}
        input.char-input {{ width: 100%; padding: 8px; border: 2px solid #ddd; border-radius: 4px; font-size: 14px; text-align: center; margin-top: 5px; }}
        input.char-input:focus {{ border-color: #1976d2; outline: none; }}
        .actions {{ margin-top: 10px; display: flex; gap: 5px; }}
        .actions button {{ flex: 1; padding: 6px; font-size: 12px; }}
        svg.glyph {{ width: 60px; height: 60px; }}
    </style>
</head>
<body>
    <h1>🔤 {title}</h1>

    <div class="summary">
        <div class="stat-item">
            <div class="stat-label">总签名数</div>
            <div class="stat-value">{len(self.collected)}</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">已知签名</div>
            <div class="stat-value">{len([s for s in self.collected if s in known_sigs])}</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">未知签名</div>
            <div class="stat-value">{len([s for s in self.collected if s not in known_sigs])}</div>
        </div>
        <div class="stat-item">
            <div class="stat-label">识别率</div>
            <div class="stat-value">{100 * len([s for s in self.collected if s in known_sigs]) / len(self.collected):.1f}%</div>
        </div>
    </div>

    <div class="controls">
        <div class="filter-group">
            <label><input type="checkbox" id="showUnknown" checked> 显示未知</label>
            <label><input type="checkbox" id="showKnown" checked> 显示已知</label>
        </div>
        <button onclick="exportData()">📥 导出为JSON</button>
        <button onclick="copyAllUnknown()">📋 复制未知签名</button>
    </div>

    <div class="grid" id="grid">
'''

        for sig, info in sorted_sigs:
            if info.count < 1:
                continue

            known_char = known_sigs.get(sig, "")
            card_class = "known" if known_char else "unknown"

            # 生成字形SVG
            path_d = info.paths[0] if info.paths else ""
            if path_d:
                svg_content = f'''<svg class="glyph" xmlns="http://www.w3.org/2000/svg" viewBox="-5 -15 25 25">
                    <path d="{path_d}" fill="#333" stroke="none" transform="scale(0.8,-0.8)"/>
                </svg>'''
            else:
                svg_content = '<div class="glyph">?</div>'

            sources_text = f"来自: {', '.join(info.sources[:3])}" if info.sources else ""

            html += f'''
        <div class="card {card_class}" data-sig="{sig}" data-known="{1 if known_char else 0}">
            {svg_content}
            <div class="sig">{sig}</div>
            <div class="count">出现 {info.count} 次</div>
            <div class="current-char">{known_char or "?"}</div>
            {f'<div class="sources">{sources_text}</div>' if sources_text else ''}
            <input type="text" class="char-input" value="{known_char}" placeholder="LaTeX字符">
            <div class="actions">
                <button onclick="copyToClipboard(this)">复制</button>
            </div>
        </div>
'''

        html += '''
    </div>

    <script>
        const knownSigs = ''' + json.dumps(known_sigs) + ''';

        function filterCards() {
            const showUnknown = document.getElementById('showUnknown').checked;
            const showKnown = document.getElementById('showKnown').checked;

            document.querySelectorAll('.card').forEach(card => {
                const isKnown = card.dataset.known === '1';
                if ((isKnown && showKnown) || (!isKnown && showUnknown)) {
                    card.style.display = '';
                } else {
                    card.style.display = 'none';
                }
            });
        }

        function exportData() {
            const cards = document.querySelectorAll('.card');
            const mapping = {};
            let newCount = 0;

            cards.forEach(card => {
                const sig = card.dataset.sig;
                const char = card.querySelector('.char-input').value.trim();
                if (char) {
                    mapping[sig] = char;
                    if (!knownSigs[sig]) newCount++;
                }
            });

            const json = JSON.stringify(mapping, null, 2);
            const blob = new Blob([json], {type: 'application/json'});
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'glyph_signatures.json';
            a.click();

            alert('已导出 ' + Object.keys(mapping).length + ' 个签名\\n其中新增 ' + newCount + ' 个');
        }

        function copyAllUnknown() {
            const unknown = [];
            document.querySelectorAll('.card.unknown').forEach(card => {
                if (card.style.display !== 'none') {
                    unknown.push(card.dataset.sig);
                }
            });

            const text = unknown.join('\\n');
            navigator.clipboard.writeText(text).then(() => {
                alert('已复制 ' + unknown.length + ' 个未知签名到剪贴板');
            });
        }

        function copyToClipboard(btn) {
            const sig = btn.closest('.card').dataset.sig;
            navigator.clipboard.writeText(sig).then(() => {
                btn.textContent = '✓';
                setTimeout(() => { btn.textContent = '复制'; }, 1000);
            });
        }

        document.getElementById('showUnknown').addEventListener('change', filterCards);
        document.getElementById('showKnown').addEventListener('change', filterCards);

        document.querySelectorAll('.char-input').forEach(input => {
            input.addEventListener('input', function() {
                const card = this.closest('.card');
                const charDisplay = card.querySelector('.current-char');
                charDisplay.textContent = this.value || '?';

                if (this.value.trim()) {
                    card.classList.remove('unknown');
                    card.classList.add('known');
                } else {
                    card.classList.remove('known');
                    card.classList.add('unknown');
                }
            });
        });
    </script>
</body>
</html>
'''

        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(html)
            print(f"✓ 已生成: {output_path}")
            return True
        except Exception as e:
            print(f"✗ 生成失败: {e}")
            return False


def main():
    """命令行入口示例"""
    import argparse

    parser = argparse.ArgumentParser(
        description="签名映射表扩展工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 查看现有映射
  %(prog)s list

  # 添加单个映射
  %(prog)s add a1b2c3d4 "\\\\alpha"

  # 从题目收集签名
  %(prog)s collect -q 29811335 29811336 29811337

  # 合并另一个JSON文件
  %(prog)s merge other_sigs.json

  # 导出当前映射
  %(prog)s export output.json
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # list命令
    list_parser = subparsers.add_parser('list', help='列出所有映射')
    list_parser.add_argument('-f', '--filter', help='过滤字符')

    # add命令
    add_parser = subparsers.add_parser('add', help='添加映射')
    add_parser.add_argument('signature', help='签名（8位）')
    add_parser.add_argument('character', help='LaTeX字符')

    # collect命令
    collect_parser = subparsers.add_parser('collect', help='从题目收集签名')
    collect_parser.add_argument('-q', '--questions', nargs='+', required=True, help='题目ID列表')
    collect_parser.add_argument('-o', '--output', default='signature_analyzer.html', help='输出HTML文件')

    # merge命令
    merge_parser = subparsers.add_parser('merge', help='合并JSON文件')
    merge_parser.add_argument('json_file', help='要合并的JSON文件')

    # export命令
    export_parser = subparsers.add_parser('export', help='导出映射')
    export_parser.add_argument('output', help='输出文件路径')

    args = parser.parse_args()

    mapper = SignatureMapper()

    if args.command == 'list':
        mapper.list_all(filter_char=args.filter if hasattr(args, 'filter') else None)

    elif args.command == 'add':
        mapper.add(args.signature, args.character)

    elif args.command == 'collect':
        collector = SignatureCollector()
        print(f"\n正在从 {len(args.questions)} 个题目收集签名...")
        stats = collector.collect_from_questions(args.questions)
        print(f"\n收集统计: {collector.get_statistics()}")

        # 显示未知签名
        unknown = collector.get_unknown_signatures(mapper)
        print(f"\n发现 {len(unknown)} 个未知签名:")
        for sig, info in unknown[:10]:
            print(f"  {sig}: 出现 {info.count} 次")
        if len(unknown) > 10:
            print(f"  ... 还有 {len(unknown) - 10} 个")

        # 生成HTML
        collector.export_html(args.output, mapper)
        print(f"\n请打开 {args.output} 进行标注")

    elif args.command == 'merge':
        mapper.merge(args.json_file)

    elif args.command == 'export':
        mapper.export(args.output)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
