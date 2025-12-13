import asyncio
import sys
import os
import json
from mcp_server.server import ExamPaperMCPServer
from mcp.types import Tool
from mcp.server.stdio import stdio_server

# 模拟 stdio 环境
# 将输出重定向到临时文件以便检查
import io

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
    if os.getcwd() not in sys.path:
        sys.path.append(os.getcwd())
    asyncio.run(test_server_startup())
