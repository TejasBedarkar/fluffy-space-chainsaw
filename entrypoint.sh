#!/bin/bash

# Function to kill child processes
cleanup() {
    echo "🛑 Shutting down processes..."
    kill $(jobs -p) 2>/dev/null
    exit
}

trap cleanup SIGINT SIGTERM EXIT

# --- RAILWAY FIX ---
# Railway provides the port in the $PORT variable.
# We default to 8000 if running locally, but use $PORT on Railway.
PORT="${PORT:-8000}"

echo "🚀 Starting FastAPI Backend on PORT $PORT..."

# CRITICAL: We bind uvicorn to 0.0.0.0 and the dynamic $PORT
uvicorn server:app --host 0.0.0.0 --port $PORT &

# Start AI Agent
echo "🤖 Starting AI Agent..."
python agent/agent.py start &

# Wait forever
wait
