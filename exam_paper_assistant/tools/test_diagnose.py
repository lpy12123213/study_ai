"""
测试MCP诊断工具
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT_DIR / ".local" / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT_DIR))

from mcp_server.server import ExamPaperMCPServer

async def test_diagnose():
    print("=== Test MCP Diagnose Tool ===\n")

    server = ExamPaperMCPServer()

    # 初始化crawler
    from crawler.zujuan_crawler import ZujuanCrawler
    server.crawler = ZujuanCrawler()
    await server.crawler.initialize()

    try:
        # 调用诊断方法
        result = await server._diagnose_export(test_question_id="70287")

        # 保存结果到文件
        output_path = ARTIFACTS_DIR / "diagnose_result.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"Result saved to {output_path}")

        # 打印关键信息
        print(f"\nOverall Status: {result.get('overall_status', 'unknown')}")
        print(f"Issues: {len(result.get('issues', []))}")
        for issue in result.get("issues", []):
            print(f"  - {issue}")
        print(f"Recommendations: {len(result.get('recommendations', []))}")
        for rec in result.get("recommendations", []):
            print(f"  - {rec}")

        # API测试结果
        for check in result.get("checks", []):
            if check.get("name") == "API连通性测试":
                details = check.get("details", {})
                add_q = details.get("add_question", {})
                print(f"\nAPI Test:")
                print(f"  Status: {check.get('status')}")
                print(f"  Question Added: {add_q.get('question_added')}")
                if add_q.get("response"):
                    print(f"  Questions in Response: {add_q['response'].get('questions_count')}")
                    print(f"  Question IDs: {add_q['response'].get('question_ids_returned')}")

    finally:
        if server.crawler:
            await server.crawler.close()

if __name__ == "__main__":
    asyncio.run(test_diagnose())
