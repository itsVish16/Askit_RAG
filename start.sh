#!/usr/bin/env bash
set -e

# ==============================================================================
# Askit RAG - One-Command Startup Script
# Boots:
#   1. Qdrant Vector Engine (Docker on port 6333)
#   2. FastAPI + LangGraph Backend (Uvicorn on port 8000)
#   3. Next.js Frontend Dashboard (Node on port 3000)
# ==============================================================================

echo "=========================================="
echo "🚀 Starting Askit RAG Full-Stack System"
echo "=========================================="

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

# 1. Ensure Qdrant Vector Engine is Running
echo ""
echo "[1/3] Checking Qdrant Vector Database..."
if docker ps --format '{{.Names}}' | grep -q "^askit-qdrant$"; then
    echo "  ✅ Qdrant is already running on http://localhost:6333"
elif docker ps -a --format '{{.Names}}' | grep -q "^askit-qdrant$"; then
    echo "  📦 Resuming existing askit-qdrant container..."
    docker start askit-qdrant > /dev/null
    echo "  ✅ Qdrant started on http://localhost:6333"
else
    echo "  📦 Launching new askit-qdrant container..."
    mkdir -p "$ROOT_DIR/backend/data/qdrant_storage"
    docker run -d --name askit-qdrant -p 6333:6333 -p 6334:6334 -v "$ROOT_DIR/backend/data/qdrant_storage:/qdrant/storage" qdrant/qdrant > /dev/null
    echo "  ✅ Qdrant started on http://localhost:6333"
fi

# Trap signals for graceful shutdown on Ctrl+C
cleanup() {
    echo ""
    echo "🛑 Shutting down Askit services..."
    if [ -n "$BACKEND_PID" ]; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    if [ -n "$FRONTEND_PID" ]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    echo "👋 Shutdown complete."
    exit 0
}
trap cleanup SIGINT SIGTERM

# 2. Start FastAPI Backend (Port 8000)
echo ""
echo "[2/3] Starting FastAPI + LangGraph Backend (Port 8000)..."
cd "$ROOT_DIR/backend"
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# 3. Start Next.js Frontend (Port 3000)
echo ""
echo "[3/3] Starting Next.js Frontend (Port 3000)..."
cd "$ROOT_DIR/frontend"
npm run dev &
FRONTEND_PID=$!

cd "$ROOT_DIR"

echo ""
echo "=========================================="
echo "✨ Askit RAG is UP and RUNNING!"
echo "=========================================="
echo "  👉 Frontend UI:      http://localhost:3000"
echo "  👉 Backend API Docs: http://localhost:8000/docs"
echo "  👉 Qdrant Dashboard: http://localhost:6333/dashboard"
echo "=========================================="
echo "Press Ctrl+C to stop all services cleanly."
echo ""

wait
