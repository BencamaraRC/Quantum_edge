"""Prometheus metrics for monitoring."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, Info

# ─── Agent metrics ───
AGENT_INFO = Info("qe_agent", "Agent information")
AGENT_CYCLES = Counter(
    "qe_agent_cycles_total",
    "Total agent cycle executions",
    ["agent_name"],
)
AGENT_CYCLE_DURATION = Histogram(
    "qe_agent_cycle_duration_seconds",
    "Agent cycle execution duration",
    ["agent_name"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
AGENT_ERRORS = Counter(
    "qe_agent_errors_total",
    "Total agent errors",
    ["agent_name", "error_type"],
)

# ─── Message bus metrics ───
MESSAGES_PUBLISHED = Counter(
    "qe_messages_published_total",
    "Messages published to Redis Streams",
    ["stream"],
)
MESSAGES_CONSUMED = Counter(
    "qe_messages_consumed_total",
    "Messages consumed from Redis Streams",
    ["stream", "consumer_group"],
)
MESSAGE_LAG = Gauge(
    "qe_message_lag",
    "Consumer group message lag",
    ["stream", "consumer_group"],
)

# ─── Pipeline metrics ───
MEMOS_CREATED = Counter("qe_memos_created_total", "Investment memos created")
MEMOS_COMPLETED = Counter(
    "qe_memos_completed_total",
    "Investment memos completed",
    ["result"],  # passed, rejected, timed_out, cancelled
)
PIPELINE_DURATION = Histogram(
    "qe_pipeline_duration_seconds",
    "Full pipeline duration from signal to decision",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)
PASS1_SCORES = Histogram(
    "qe_pass1_scores",
    "Pass 1 composite scores",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0],
)
PASS2_SCORES = Histogram(
    "qe_pass2_scores",
    "Pass 2 composite scores",
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 1.0],
)

# ─── Trading metrics ───
ORDERS_SUBMITTED = Counter(
    "qe_orders_submitted_total",
    "Orders submitted to broker",
    ["side", "order_type"],
)
ORDERS_FILLED = Counter(
    "qe_orders_filled_total",
    "Orders filled",
    ["side"],
)
POSITION_VALUE = Gauge("qe_position_value_dollars", "Current position value", ["symbol"])
DAILY_PNL = Gauge("qe_daily_pnl_dollars", "Daily P&L")
PORTFOLIO_EQUITY = Gauge("qe_portfolio_equity_dollars", "Portfolio equity")

# ─── Risk metrics ───
RISK_CHECKS_PASSED = Counter("qe_risk_checks_passed_total", "Risk checks passed")
RISK_CHECKS_VETOED = Counter(
    "qe_risk_checks_vetoed_total",
    "Risk checks vetoed",
    ["reason"],
)
CIRCUIT_BREAKER_TRIGGERS = Counter(
    "qe_circuit_breaker_triggers_total",
    "Circuit breaker activations",
)
