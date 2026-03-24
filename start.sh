#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="/opt/anaconda3/bin/python"
UVICORN="/opt/anaconda3/bin/uvicorn"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo "============================================"
echo "  Quantum Edge — Paper Trading System"
echo "  Starting $(date)"
echo "============================================"

# Check Redis
if ! redis-cli ping > /dev/null 2>&1; then
  echo "ERROR: Redis not running. Start it with: brew services start redis"
  exit 1
fi
echo "[OK] Redis"

# Check PostgreSQL
if ! /opt/homebrew/opt/postgresql@16/bin/pg_isready -p 5433 > /dev/null 2>&1; then
  echo "ERROR: PostgreSQL not running on port 5433. Start it with: brew services start postgresql@16"
  exit 1
fi
echo "[OK] PostgreSQL"

# Check Alpaca keys
source .env 2>/dev/null || true
if [ -z "${ALPACA_API_KEY:-}" ]; then
  echo "ERROR: ALPACA_API_KEY not set in .env"
  exit 1
fi
echo "[OK] Alpaca keys configured"

# Initialize Redis streams
echo ""
echo "Initializing Redis streams..."
$PYTHON -c "
import asyncio
from infrastructure.scripts.init_redis_streams import init_streams
asyncio.run(init_streams('redis://localhost:6379/0'))
" 2>&1 | tail -1

# Kill any previous instances
echo ""
echo "Cleaning up old processes..."
pkill -f "uvicorn quantum_edge.api" 2>/dev/null || true
pkill -f "coordinator.main" 2>/dev/null || true
pkill -f "agents.agent_0" 2>/dev/null || true
sleep 2

# Start API
echo "Starting API (port 8001)..."
$UVICORN quantum_edge.api:app --host 0.0.0.0 --port 8001 \
  > "$LOG_DIR/api.log" 2>&1 &
echo "  PID: $!"

# Start Coordinator
echo "Starting Coordinator..."
$PYTHON -m coordinator.main \
  > "$LOG_DIR/coordinator.log" 2>&1 &
echo "  PID: $!"

# Start all 8 agents
AGENTS=(
  "agent_01_news_scanner"
  "agent_02_market_data"
  "agent_03_events_engine"
  "agent_04_momentum_bot"
  "agent_05_risk_guard"
  "agent_06_data_scientist"
  "agent_07_smart_money"
  "agent_08_position_monitor"
)

for agent in "${AGENTS[@]}"; do
  echo "Starting $agent..."
  AGENT_NAME="$agent" $PYTHON -m "agents.${agent}.main" \
    > "$LOG_DIR/${agent}.log" 2>&1 &
  echo "  PID: $!"
done

sleep 3

# Verify
echo ""
echo "============================================"
echo "  System Status"
echo "============================================"
echo ""

# Check Alpaca account
$PYTHON -c "
import os, requests
from dotenv import load_dotenv
load_dotenv()
r = requests.get('https://paper-api.alpaca.markets/v2/account',
    headers={'APCA-API-KEY-ID': os.getenv('ALPACA_API_KEY'),
             'APCA-API-SECRET-KEY': os.getenv('ALPACA_SECRET_KEY')})
a = r.json()
print(f'  Alpaca Paper: \${float(a[\"equity\"]):,.2f} equity')
print(f'  Buying Power: \${float(a[\"buying_power\"]):,.2f}')
print(f'  Status: {a[\"status\"]}')
" 2>/dev/null

echo ""
RUNNING=$(ps aux | grep -c "[a]gents.agent_0")
echo "  Agents running: $RUNNING/8"
echo "  API: http://localhost:8001/health"
echo "  Dashboard: http://localhost:5174/pipeline"
echo ""
echo "  Logs: tail -f logs/*.log"
echo "  Stop: pkill -f 'quantum_edge\|coordinator\|agents.agent'"
echo ""
echo "  Market hours: Mon-Fri 9:30am-4:00pm ET"
echo "============================================"
