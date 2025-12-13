"""
测试修复后的导出功能
"""
import asyncio
import sys
from pathlib import Path

# 添加路径
sys.path.insert(0, str(Path(__file__).parent))

from crawler.zujuan_crawler import ZujuanCrawler

async def test_export_fix():
    print("=== 测试修复后的导出功能 ===")

    crawler = ZujuanCrawler()
    await crawler.initialize()

    try:
        # 测试导出单个题目
        test_question_ids = ["70287"]  # 测试题目ID

        print(f"\n导出题目: {test_question_ids}")
        result = await crawler.export_to_basket(
            question_ids=test_question_ids,
            auto_login=False
        )

        print(f"\n导出结果:")
        for key, value in result.items():
            if key == "api_response":
                print(f"  {key}: ")
                if isinstance(value, dict):
                    print(f"    serverVersion: {value.get('serverVersion')}")
                    questions = value.get('questions', [])
                    print(f"    questions count: {len(questions)}")
                    for q in questions[:3]:
                        print(f"      - questionId: {q.get('questionId')}")
            else:
                print(f"  {key}: {value}")

        if result.get("success"):
            print("\n*** 导出成功! ***")
        else:
            print(f"\n*** 导出失败: {result.get('error')} ***")

    finally:
        await crawler.close()

if __name__ == "__main__":
    asyncio.run(test_export_fix())
