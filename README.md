# Quantum Edge

Autonomous AI-powered day trading platform with a 7-agent architecture, double-confirmation conviction pipeline, and multi-layered risk management.

## Quick Start

```bash
# Start infrastructure (Redis + TimescaleDB)
docker-compose -f docker-compose.infra.yml up -d

# Install dependencies
poetry install

# Run tests
poetry run pytest tests/unit/

# Start all agents
docker-compose up
```

## Architecture

- **Choreography-with-Coordinator** pattern on Redis Streams
- **7 autonomous agents** sharing context via dual-write pattern (Redis Hash + Stream)
- **Investment Memo** as central knowledge object assembled through pipeline
- **Double-confirmation** pipeline (Pass 1 → Smart Money → Pass 2)
- **Agent 5 veto authority** on all trades
