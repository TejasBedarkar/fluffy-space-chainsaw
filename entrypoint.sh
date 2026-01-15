#!/bin/bash

# Function to kill child processes
cleanup() {
    echo "🛑 Shutting down processes..."
    kill $(jobs -p) 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM EXIT

# --- RAILWAY FIX: Use the $PORT variable ---
# If Railway gives a port, use it. Otherwise, use 8000.
PORT="${PORT:-8000}"

echo "🚀 Starting FastAPI Backend on PORT $PORT..."
uvicorn server:app --host 0.0.0.0 --port $PORT &

# Start AI Agent
echo "🤖 Starting AI Agent..."
python agent/agent.py start &

wait
