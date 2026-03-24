-- Quantum Edge TimescaleDB Schema
-- Runs on first docker-compose up via init.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Investment Memos (permanent storage)
CREATE TABLE IF NOT EXISTS investment_memos (
    memo_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    phase TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_memos_symbol ON investment_memos (symbol);
CREATE INDEX idx_memos_phase ON investment_memos (phase);
CREATE INDEX idx_memos_created ON investment_memos (created_at DESC);

-- Agent Signals (time-series)
CREATE TABLE IF NOT EXISTS agent_signals (
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    direction TEXT,
    score DOUBLE PRECISION,
    conviction TEXT,
    pass_number INTEGER,
    memo_id TEXT,
    data JSONB,
    idempotency_key TEXT UNIQUE
);

SELECT create_hypertable('agent_signals', 'time', if_not_exists => TRUE);
CREATE INDEX idx_signals_symbol ON agent_signals (symbol, time DESC);
CREATE INDEX idx_signals_agent ON agent_signals (agent_id, time DESC);

-- Trade Log (time-series)
CREATE TABLE IF NOT EXISTS trades (
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    memo_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry_price DOUBLE PRECISION,
    stop_loss DOUBLE PRECISION,
    take_profit DOUBLE PRECISION,
    exit_price DOUBLE PRECISION,
    pnl DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,
    status TEXT NOT NULL,
    broker TEXT NOT NULL DEFAULT 'alpaca',
    order_id TEXT,
    data JSONB
);

SELECT create_hypertable('trades', 'time', if_not_exists => TRUE);
CREATE INDEX idx_trades_symbol ON trades (symbol, time DESC);
CREATE INDEX idx_trades_memo ON trades (memo_id);

-- Portfolio Snapshots (time-series, every 30s from Agent 5)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    equity DOUBLE PRECISION NOT NULL,
    cash DOUBLE PRECISION NOT NULL,
    buying_power DOUBLE PRECISION NOT NULL,
    daily_pnl DOUBLE PRECISION DEFAULT 0,
    daily_pnl_pct DOUBLE PRECISION DEFAULT 0,
    total_exposure_pct DOUBLE PRECISION DEFAULT 0,
    open_positions INTEGER DEFAULT 0,
    circuit_breaker_active BOOLEAN DEFAULT FALSE,
    data JSONB
);

SELECT create_hypertable('portfolio_snapshots', 'time', if_not_exists => TRUE);

-- Regime History (from Agent 6)
CREATE TABLE IF NOT EXISTS regime_history (
    time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    regime TEXT NOT NULL,
    regime_probability DOUBLE PRECISION,
    hmm_state INTEGER,
    vol_forecast DOUBLE PRECISION,
    anomaly_detected BOOLEAN DEFAULT FALSE,
    data JSONB
);

SELECT create_hypertable('regime_history', 'time', if_not_exists => TRUE);

-- Model Artifacts Metadata (Agent 6 learning loop)
CREATE TABLE IF NOT EXISTS model_artifacts (
    id SERIAL PRIMARY KEY,
    model_type TEXT NOT NULL,
    version TEXT NOT NULL,
    s3_path TEXT,
    metrics JSONB,
    trained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (model_type, version)
);

-- Continuous Aggregates for dashboard
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_pnl_summary
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS day,
    SUM(pnl) AS total_pnl,
    COUNT(*) AS trade_count,
    COUNT(*) FILTER (WHERE pnl > 0) AS winning_trades,
    COUNT(*) FILTER (WHERE pnl <= 0) AS losing_trades,
    AVG(pnl) AS avg_pnl,
    MAX(pnl) AS best_trade,
    MIN(pnl) AS worst_trade
FROM trades
GROUP BY day
WITH NO DATA;

SELECT add_continuous_aggregate_policy('daily_pnl_summary',
    start_offset => INTERVAL '7 days',
    end_offset => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists => TRUE
);
