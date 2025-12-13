#!/usr/bin/env python3
"""
快速启动脚本：SVG公式签名映射扩展
支持快捷命令行操作
"""
import sys
import os

# 添加utils目录到Python路径
sys.path.insert(0, os.path.dirname(__file__))

from signature_extender import SignatureMapper, SignatureCollector


def quick_add(signature: str, character: str):
    """快速添加单个映射"""
    mapper = SignatureMapper()
    mapper.add(signature, character)


def quick_collect(question_ids: list, output_file: str = 'signature_analyzer.html'):
    """快速收集和分析签名"""
    print(f"\n{'='*60}")
    print("SVG公式字形签名收集工具")
    print(f"{'='*60}\n")

    mapper = SignatureMapper()
    collector = SignatureCollector()

    print(f"🔍 从 {len(question_ids)} 个题目收集签名...")
    stats = collector.collect_from_questions(question_ids)

    # 显示统计信息
    print(f"\n{'='*60}")
    print("收集统计")
    print(f"{'='*60}")
    info = collector.get_statistics()
    print(f"  总签名数: {info['total_signatures']}")
    print(f"  总出现次: {info['total_occurrences']}")
    print(f"  来源题目: {info['total_sources']}")

    # 计算已知率
    known_count = len([s for s in collector.collected if s in mapper.signatures])
    unknown_count = len(collector.collected) - known_count
    recognition_rate = 100 * known_count / len(collector.collected) if collector.collected else 0

    print(f"\n  已识别: {known_count}/{len(collector.collected)} ({recognition_rate:.1f}%)")
    print(f"  未识别: {unknown_count}")

    # 显示高频未知签名
    unknown = collector.get_unknown_signatures(mapper)
    if unknown:
        print(f"\n🔤 高频未知签名 (Top 10):")
        for sig, info in unknown[:10]:
            print(f"  {sig}: {info.count}次")

    # 生成HTML
    print(f"\n💾 生成分析页面: {output_file}")
    collector.export_html(output_file, mapper)

    print(f"\n✓ 完成！请打开 {output_file} 进行标注")
    print(f"  步骤:")
    print(f"    1. 在输入框中填写对应的LaTeX字符")
    print(f"    2. 点击'导出为JSON'下载签名映射")
    print(f"    3. 运行: python signature_extender.py merge glyph_signatures.json")
    print(f"{'='*60}\n")

    return output_file


def quick_list(filter_str: str = ""):
    """快速列出映射"""
    mapper = SignatureMapper()
    mapper.list_all(filter_char=filter_str if filter_str else None)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("SVG公式签名映射扩展 - 快速启动脚本\n")
        print("用法:")
        print("  python quick_start.py add <sig> <char>     - 添加单个映射")
        print("  python quick_start.py collect <qid> [qid...] - 收集和分析签名")
        print("  python quick_start.py list [filter]         - 列出所有映射\n")
        print("示例:")
        print("  python quick_start.py collect 29811335 29811336 29811337")
        print("  python quick_start.py add a1b2c3d4 '\\\\alpha'")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 4:
        quick_add(sys.argv[2], sys.argv[3])

    elif cmd == "collect":
        qids = sys.argv[2:]
        output = "signature_analyzer.html"
        if "-o" in qids:
            idx = qids.index("-o")
            output = qids[idx + 1]
            qids = [q for q in qids if q not in ("-o", output)]
        quick_collect(qids, output)

    elif cmd == "list":
        filter_str = sys.argv[2] if len(sys.argv) > 2 else ""
        quick_list(filter_str)

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)
