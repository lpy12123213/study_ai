"""
未知公式签名记录模块

在AI使用MCP搜索题目时，将无法识别的公式签名记录到文件中，
以便后续分析并添加到签名库中。

文件位置: utils/unknown_signatures.json
"""

import json
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

from backend.core.logging_utils import get_logger

# 未知签名记录文件路径
UNKNOWN_SIGNATURES_FILE = os.path.join(os.path.dirname(__file__), "unknown_signatures.json")

# 线程锁，确保并发安全
_file_lock = threading.Lock()

logger = get_logger(__name__)

# 内存缓存，减少文件读写
_cache: Optional[Dict] = None
_cache_dirty = False


def _load_records() -> Dict:
    """加载未知签名记录"""
    global _cache

    if _cache is not None:
        return _cache

    if os.path.exists(UNKNOWN_SIGNATURES_FILE):
        try:
            with open(UNKNOWN_SIGNATURES_FILE, "r", encoding="utf-8") as f:
                _cache = json.load(f)
        except Exception:
            _cache = {"signatures": {}, "stats": {"total_occurrences": 0}}
    else:
        _cache = {"signatures": {}, "stats": {"total_occurrences": 0}}

    return _cache


def _save_records(records: Dict) -> None:
    """保存未知签名记录到文件"""
    global _cache_dirty

    try:
        with open(UNKNOWN_SIGNATURES_FILE, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        _cache_dirty = False
    except Exception as e:
        logger.warning("failed to save unknown signatures record", extra={"error": str(e)})


def record_unknown_signatures(
    unknown_sigs: List[str], source_url: Optional[str] = None, context: Optional[str] = None
) -> int:
    """
    记录未知签名

    Args:
        unknown_sigs: 未知签名列表
        source_url: 来源URL（公式的SVG URL）
        context: 上下文信息（如所在题目的题干摘要）

    Returns:
        新增的签名数量
    """
    if not unknown_sigs:
        return 0

    global _cache_dirty
    new_count = 0
    timestamp = datetime.now().isoformat()

    with _file_lock:
        records = _load_records()

        for sig in unknown_sigs:
            if not sig:
                continue

            if sig not in records["signatures"]:
                # 新签名
                records["signatures"][sig] = {
                    "first_seen": timestamp,
                    "last_seen": timestamp,
                    "count": 1,
                    "sources": [],
                    "status": "pending",  # pending, analyzed, added
                }
                new_count += 1
            else:
                # 已存在的签名，更新计数
                records["signatures"][sig]["count"] += 1
                records["signatures"][sig]["last_seen"] = timestamp

            # 记录来源（最多保存10个）
            if source_url:
                sources = records["signatures"][sig]["sources"]
                # 避免重复
                if source_url not in sources:
                    if len(sources) >= 10:
                        sources.pop(0)  # 移除最旧的
                    sources.append(source_url)

            records["stats"]["total_occurrences"] += 1

        # 更新统计
        records["stats"]["last_updated"] = timestamp
        records["stats"]["unique_count"] = len(records["signatures"])

        _cache_dirty = True

        # 立即保存（确保数据不丢失）
        _save_records(records)

    return new_count


def get_unknown_signatures_summary() -> Dict:
    """
    获取未知签名摘要

    Returns:
        包含统计信息和高频未知签名的摘要
    """
    with _file_lock:
        records = _load_records()

        # 按出现次数排序
        sorted_sigs = sorted(records["signatures"].items(), key=lambda x: x[1]["count"], reverse=True)

        # 获取待处理的高频签名（前20个）
        pending_high_freq = [
            {
                "signature": sig,
                "count": data["count"],
                "first_seen": data["first_seen"],
                "sources": data["sources"][:3],  # 最多3个来源
            }
            for sig, data in sorted_sigs
            if data.get("status") == "pending"
        ][:20]

        return {
            "total_unique": records["stats"].get("unique_count", 0),
            "total_occurrences": records["stats"].get("total_occurrences", 0),
            "last_updated": records["stats"].get("last_updated"),
            "pending_count": sum(1 for sig, data in records["signatures"].items() if data.get("status") == "pending"),
            "high_frequency_pending": pending_high_freq,
        }


def mark_signature_status(signature: str, status: str) -> bool:
    """
    标记签名状态

    Args:
        signature: 签名
        status: 状态 ('pending', 'analyzed', 'added')

    Returns:
        是否成功
    """
    with _file_lock:
        records = _load_records()

        if signature in records["signatures"]:
            records["signatures"][signature]["status"] = status
            _save_records(records)
            return True

        return False


def clear_added_signatures() -> int:
    """
    清理已添加到签名库的记录

    Returns:
        清理的数量
    """
    with _file_lock:
        records = _load_records()

        # 找出已添加的签名
        to_remove = [sig for sig, data in records["signatures"].items() if data.get("status") == "added"]

        # 移除
        for sig in to_remove:
            del records["signatures"][sig]

        # 更新统计
        records["stats"]["unique_count"] = len(records["signatures"])

        _save_records(records)

        return len(to_remove)


def export_for_analysis(output_path: Optional[str] = None) -> str:
    """
    导出未知签名供分析

    生成一个包含所有待处理签名的报告文件

    Args:
        output_path: 输出路径，默认为同目录下的 unknown_signatures_report.txt

    Returns:
        输出文件路径
    """
    if output_path is None:
        output_path = os.path.join(os.path.dirname(__file__), "unknown_signatures_report.txt")

    with _file_lock:
        records = _load_records()

        lines = [
            "=" * 60,
            "未知公式签名分析报告",
            f"生成时间: {datetime.now().isoformat()}",
            "=" * 60,
            "",
            f"总计未知签名数: {records['stats'].get('unique_count', 0)}",
            f"总计出现次数: {records['stats'].get('total_occurrences', 0)}",
            "",
            "-" * 60,
            "待处理签名（按出现频率排序）:",
            "-" * 60,
            "",
        ]

        # 按出现次数排序
        sorted_sigs = sorted(records["signatures"].items(), key=lambda x: x[1]["count"], reverse=True)

        for sig, data in sorted_sigs:
            if data.get("status") != "pending":
                continue

            lines.append(f"签名: {sig}")
            lines.append(f"  出现次数: {data['count']}")
            lines.append(f"  首次发现: {data['first_seen']}")
            if data.get("sources"):
                lines.append("  示例来源:")
                for src in data["sources"][:3]:
                    lines.append(f"    - {src}")
            lines.append("")

        lines.append("-" * 60)
        lines.append("使用方法:")
        lines.append("1. 访问示例来源URL查看公式图片")
        lines.append("2. 识别对应的LaTeX字符")
        lines.append("3. 使用 svg_to_latex.add_signature('签名', 'LaTeX字符') 添加映射")
        lines.append("4. 或直接编辑 glyph_signatures.json 文件")
        lines.append("-" * 60)

        content = "\n".join(lines)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        return output_path


# 便捷函数：在公式转换后调用
def log_unknown_from_conversion(svg_url: str, unknown_sigs: List[str], context: Optional[str] = None) -> None:
    """
    记录公式转换中发现的未知签名（便捷接口）

    Args:
        svg_url: SVG公式URL
        unknown_sigs: 未知签名列表
        context: 上下文（可选）
    """
    if unknown_sigs:
        record_unknown_signatures(unknown_sigs=unknown_sigs, source_url=svg_url, context=context)


if __name__ == "__main__":
    # 测试
    print("测试未知签名记录模块")

    # 模拟记录
    test_sigs = ["abc12345", "def67890"]
    count = record_unknown_signatures(test_sigs, source_url="https://example.com/formula/test.svg", context="测试题目")
    print(f"新增签名数: {count}")

    # 获取摘要
    summary = get_unknown_signatures_summary()
    print(f"摘要: {summary}")

    # 导出报告
    report_path = export_for_analysis()
    print(f"报告已导出: {report_path}")
