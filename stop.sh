#!/usr/bin/env bash
echo "Stopping Quantum Edge..."
pkill -f "uvicorn quantum_edge.api" 2>/dev/null || true
pkill -f "coordinator.main" 2>/dev/null || true
pkill -f "agents.agent_0" 2>/dev/null || true
sleep 1
echo "All processes stopped."
