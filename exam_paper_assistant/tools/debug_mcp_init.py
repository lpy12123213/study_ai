import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from mcp_server.server import ExamPaperMCPServer

async def test_server_startup():
    print("Testing server initialization...")
    try:
        server = ExamPaperMCPServer()
        print("Server initialized successfully")
        
        # 尝试手动调用 list_tools 注册的函数
        # 注意：这需要深入到 server 对象内部，可能比较复杂
        # 我们这里主要测试 import 和 init 是否报错
        
    except Exception as e:
        print(f"Server initialization failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_server_startup())
