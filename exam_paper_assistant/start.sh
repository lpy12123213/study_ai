#!/bin/bash

echo "===================================="
echo "智能组卷辅助系统 - 启动脚本"
echo "===================================="
echo ""

# 检查Python是否安装
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到Python，请先安装Python 3.8+"
    exit 1
fi

echo "[1/5] 检查虚拟环境..."
if [ ! -d "venv" ]; then
    echo "未找到虚拟环境，正在创建..."
    python3 -m venv venv
    echo "虚拟环境创建完成"
fi

echo "[2/5] 激活虚拟环境..."
source venv/bin/activate

echo "[3/5] 检查依赖..."
if ! pip show fastapi &> /dev/null; then
    echo "正在安装依赖..."
    pip install -r requirements.txt
    playwright install chromium
fi

echo "[4/5] 初始化数据库..."
if [ ! -f "exam_papers.db" ]; then
    python database/models.py
fi

echo "[5/5] 检查前端依赖..."
if ! command -v npm &> /dev/null; then
    echo "[错误] 未检测到npm，请先安装Node.js"
    exit 1
fi
if [ ! -d "frontend/node_modules" ]; then
    (cd frontend && npm install)
fi

echo ""
echo "===================================="
echo "启动完成！"
echo "===================================="
echo ""
echo "后端地址: http://localhost:8000"
echo "API文档: http://localhost:8000/docs"
echo "前端地址: http://localhost:3000"
echo ""
echo "提示：MCP服务器需要单独启动"
echo "命令：python mcp_server/server.py"
echo ""
echo "===================================="
echo ""

# 启动后端（后台）和前端（前台）
python -m uvicorn backend.app:app --host 0.0.0.0 --port 8000 --reload &
backend_pid=$!
(cd frontend && npm run dev)
kill $backend_pid
