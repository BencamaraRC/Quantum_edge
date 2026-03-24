"""Pipeline event definitions for Redis Streams."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class PipelineEventType(StrEnum):
    """Events that flow through the pipeline control streams."""

    # Phase transitions
    PHASE_ADVANCE = "phase_advance"
    MEMO_CREATED = "memo_created"
    MEMO_UPDATED = "memo_updated"

    # Signal events
    SIGNAL_RECEIVED = "signal_received"
    SIGNALS_COMPLETE = "signals_complete"

    # Decision events
    PASS1_SCORED = "pass1_scored"
    PASS2_SCORED = "pass2_scored"
    SMART_MONEY_COMPLETE = "smart_money_complete"
    TECHNICAL_COMPLETE = "technical_complete"
    RISK_CHECK_COMPLETE = "risk_check_complete"

    # Execution events
    ORDER_SUBMITTED = "order_submitted"
    ORDER_FILLED = "order_filled"
    ORDER_REJECTED = "order_rejected"
    ORDER_CANCELLED = "order_cancelled"

    # Lifecycle events
    MEMO_COMPLETED = "memo_completed"
    MEMO_CANCELLED = "memo_cancelled"
    MEMO_TIMED_OUT = "memo_timed_out"
    MEMO_REJECTED = "memo_rejected"

    # Position management events
    POSITION_MONITORING_STARTED = "position_monitoring_started"
    TRAILING_STOP_ACTIVATED = "trailing_stop_activated"
    TRAILING_STOP_FILLED = "trailing_stop_filled"
    POSITION_CLOSED = "position_closed"

    # System events
    AGENT_HEARTBEAT = "agent_heartbeat"
    AGENT_ERROR = "agent_error"
    CIRCUIT_BREAKER_TRIGGERED = "circuit_breaker_triggered"
    KILL_SWITCH_ACTIVATED = "kill_switch_activated"


class PipelineEvent(BaseModel):
    """Base event published to pipeline control streams."""

    event_type: PipelineEventType
    memo_id: UUID | None = None
    symbol: str | None = None
    agent_id: str | None = None
    phase: str | None = None
    pass_number: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    idempotency_key: str = ""

    def to_stream_dict(self) -> dict[str, str]:
        """Serialize to flat dict for Redis Stream XADD."""
        return {
            "event_type": self.event_type.value,
            "memo_id": str(self.memo_id) if self.memo_id else "",
            "symbol": self.symbol or "",
            "agent_id": self.agent_id or "",
            "phase": self.phase or "",
            "pass_number": str(self.pass_number) if self.pass_number else "",
            "data": self.model_dump_json(include={"data"}),
            "timestamp": self.timestamp.isoformat(),
            "idempotency_key": self.idempotency_key,
        }

    @classmethod
    def from_stream_dict(cls, d: dict[str, str]) -> PipelineEvent:
        """Deserialize from Redis Stream XREAD result."""
        import orjson

        data = {}
        if d.get("data"):
            parsed = orjson.loads(d["data"])
            data = parsed.get("data", {})

        return cls(
            event_type=PipelineEventType(d["event_type"]),
            memo_id=UUID(d["memo_id"]) if d.get("memo_id") else None,
            symbol=d.get("symbol") or None,
            agent_id=d.get("agent_id") or None,
            phase=d.get("phase") or None,
            pass_number=int(d["pass_number"]) if d.get("pass_number") else None,
            data=data,
            timestamp=datetime.fromisoformat(d["timestamp"]) if d.get("timestamp") else datetime.utcnow(),
            idempotency_key=d.get("idempotency_key", ""),
        )


class ContextUpdateEvent(BaseModel):
    """Event published to context change streams."""

    domain: str  # regime, volatility, macro, calendar, portfolio
    agent_id: str
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    def to_stream_dict(self) -> dict[str, str]:
        import orjson

        return {
            "domain": self.domain,
            "agent_id": self.agent_id,
            "data": orjson.dumps(self.data).decode(),
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_stream_dict(cls, d: dict[str, str]) -> ContextUpdateEvent:
        import orjson

        return cls(
            domain=d["domain"],
            agent_id=d["agent_id"],
            data=orjson.loads(d["data"]) if d.get("data") else {},
            timestamp=datetime.fromisoformat(d["timestamp"]) if d.get("timestamp") else datetime.utcnow(),
        )
