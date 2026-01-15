#!/bin/bash

# Function to kill child processes (FastAPI & Agent) when this script exits
cleanup() {
    echo "🛑 Shutting down processes..."
    kill $(jobs -p) 2>/dev/null
    exit
}

# Trap SIGINT (Ctrl+C) and SIGTERM (Docker stop)
trap cleanup SIGINT SIGTERM EXIT

# 1. Start FastAPI Server
echo "🚀 Starting FastAPI Backend on port 8000..."
uvicorn server:app --host 0.0.0.0 --port 8000 &

# 2. Start AI Agent
# We bind it to port 8081 (default) but ensure it's free now
echo "🤖 Starting AI Agent..."
python agent/agent.py start &

# Wait forever (so the script doesn't exit immediately)
wait