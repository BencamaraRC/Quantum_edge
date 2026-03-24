"""Quantum Edge — FastAPI HTTP interface.

Provides REST endpoints for:
- Portfolio state
- Active memos and pipeline status
- Trade history
- Kill switch
- Health check
- Authentication (JWT)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from quantum_edge.core.auth import create_access_token, get_current_user, verify_password
from quantum_edge.core.config import settings
from quantum_edge.core.context_store import ContextStore
from quantum_edge.core.memo_factory import MemoFactory
from quantum_edge.core.memo_store import MemoStore
from quantum_edge.core.message_bus import STREAMS, MessageBus
from quantum_edge.models.events import PipelineEvent, PipelineEventType

logger = logging.getLogger(__name__)

app = FastAPI(title="Quantum Edge", version="0.1.0")

cors_origins = [o.strip() for o in settings.qe_cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# Shared instances (initialized on startup)
bus = MessageBus()
memo_store = MemoStore()
context = ContextStore()
memo_factory: MemoFactory | None = None


@app.on_event("startup")
async def startup() -> None:
    global memo_factory
    await bus.connect()
    memo_store._redis = bus.redis
    context._redis = bus.redis
    memo_factory = MemoFactory(bus, memo_store, context)
    logger.info("API started")


@app.on_event("shutdown")
async def shutdown() -> None:
    await bus.disconnect()


# ─── Auth ───


@app.post("/auth/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()) -> dict[str, str]:
    """Authenticate and return a JWT access token."""
    if (
        form_data.username != settings.qe_admin_username
        or not settings.qe_admin_password_hash
        or not verify_password(form_data.password, settings.qe_admin_password_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(form_data.username)
    return {"access_token": token, "token_type": "bearer"}


# ─── Health ───


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


# ─── Portfolio ───


@app.get("/portfolio")
async def get_portfolio(_user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Get current portfolio state from context layer."""
    data = await context.get("portfolio")
    if not data:
        raise HTTPException(404, "Portfolio state not available")
    return data


@app.get("/portfolio/live")
async def get_portfolio_live(_user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Get full portfolio state directly from Alpaca, including positions."""
    from quantum_edge.broker.alpaca import AlpacaBroker

    broker = AlpacaBroker()
    try:
        await broker.connect()
        state = await broker.get_portfolio_state()
        return {
            "equity": state.equity,
            "cash": state.cash,
            "buying_power": state.buying_power,
            "portfolio_value": state.portfolio_value,
            "daily_pnl": state.daily_pnl,
            "daily_pnl_pct": state.daily_pnl_pct,
            "total_exposure_pct": state.total_exposure_pct,
            "circuit_breaker_active": state.circuit_breaker_active,
            "circuit_breaker_reason": state.circuit_breaker_reason,
            "positions": [
                {
                    "symbol": p.symbol,
                    "qty": p.qty,
                    "side": p.side,
                    "avg_entry_price": p.avg_entry_price,
                    "current_price": p.current_price,
                    "market_value": p.market_value,
                    "unrealized_pl": p.unrealized_pl,
                    "unrealized_pl_pct": p.unrealized_pl_pct,
                    "cost_basis": p.cost_basis,
                    "asset_class": p.asset_class,
                }
                for p in state.positions
            ],
            "options_positions": [
                {
                    "symbol": op.symbol,
                    "underlying": op.underlying,
                    "option_type": op.option_type,
                    "strike": op.strike,
                    "expiration": op.expiration,
                    "qty": op.qty,
                    "side": op.side,
                    "current_price": op.current_price,
                    "market_value": op.market_value,
                    "unrealized_pl": op.unrealized_pl,
                }
                for op in state.options_positions
            ],
            "portfolio_delta": state.portfolio_delta,
            "portfolio_theta": state.portfolio_theta,
            "updated_at": state.updated_at.isoformat(),
        }
    except Exception as e:
        logger.exception("Failed to fetch live portfolio")
        raise HTTPException(502, f"Alpaca connection failed: {e}")
    finally:
        await broker.disconnect()


# ─── Context ───


@app.get("/context/{domain}")
async def get_context(domain: str, _user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Get context layer data for a domain (regime, volatility, macro, calendar, portfolio)."""
    data = await context.get(domain)
    return data or {}


# ─── Memos ───


class CreateMemoRequest(BaseModel):
    symbol: str


@app.post("/memos")
async def create_memo(req: CreateMemoRequest, _user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Manually trigger a memo for a symbol."""
    if memo_factory is None:
        raise HTTPException(503, "Memo factory not initialized")
    memo = await memo_factory.create_memo(req.symbol)
    return {"memo_id": str(memo.memo_id), "symbol": memo.symbol, "phase": memo.phase.value}


@app.get("/memos/active")
async def get_active_memos(_user: str = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get all non-terminal memos (stocks currently being investigated)."""
    try:
        memos = await memo_store.get_active_memos()
    except Exception:
        # DB unavailable — fall back to Redis scan
        memos = await memo_store.get_all_from_redis()
        memos = [m for m in memos if not m.is_terminal()]
    return [m.model_dump(mode="json") for m in memos]


@app.get("/memos/recent")
async def get_recent_memos(limit: int = 20, _user: str = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get most recent memos (active + completed)."""
    try:
        memos = await memo_store.get_recent(limit)
    except Exception:
        # DB unavailable — fall back to Redis scan
        memos = await memo_store.get_all_from_redis()
        memos.sort(key=lambda m: m.created_at, reverse=True)
        memos = memos[:limit]
    return [m.model_dump(mode="json") for m in memos]


@app.get("/memos/{memo_id}")
async def get_memo(memo_id: UUID, _user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Get a specific memo by ID."""
    memo = await memo_store.get(memo_id)
    if memo is None:
        raise HTTPException(404, "Memo not found")
    return memo.model_dump(mode="json")


# ─── Trades ───


@app.get("/trades")
async def get_trades(limit: int = 50, _user: str = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get completed trades from executed memos."""
    try:
        memos = await memo_store.get_recent(limit * 2)
    except Exception:
        memos = await memo_store.get_all_from_redis()
        memos.sort(key=lambda m: m.created_at, reverse=True)

    trades: list[dict[str, Any]] = []
    for m in memos:
        if m.phase.value != "completed" or m.execution is None:
            continue
        ex = m.execution
        entry = ex.entry_price or 0
        # Compute exit P&L from the memo's final state
        tech = m.technical_eval
        rr = tech.risk_reward_ratio if tech else 0
        trades.append({
            "time": (m.completed_at or m.updated_at or m.created_at).isoformat(),
            "symbol": m.symbol,
            "side": ex.side or "long",
            "qty": ex.qty or 0,
            "entry": entry,
            "status": ex.status or "filled",
            "order_id": ex.order_id or "",
            "rr": f"{rr:.1f}:1" if rr else "--",
            "memo_id": str(m.memo_id),
        })
        if len(trades) >= limit:
            break

    return trades


# ─── Kill Switch ───


@app.post("/kill-switch")
async def kill_switch(_user: str = Depends(get_current_user)) -> dict[str, str]:
    """Emergency kill switch — publishes KILL_SWITCH_ACTIVATED event."""
    await bus.publish(
        STREAMS["phase"],
        PipelineEvent(
            event_type=PipelineEventType.KILL_SWITCH_ACTIVATED,
            data={"reason": "Manual kill switch via API", "timestamp": datetime.utcnow().isoformat()},
        ).to_stream_dict(),
    )
    logger.critical("KILL SWITCH ACTIVATED via API")
    return {"status": "kill_switch_activated", "timestamp": datetime.utcnow().isoformat()}


# ─── Regime ───


@app.get("/regime")
async def get_regime(_user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Get current market regime."""
    data = await context.get("regime")
    return data or {"regime": "unknown"}


# ─── Agents ───

AGENT_STREAMS: dict[str, tuple[str, str]] = {
    "agent_01": (STREAMS["news"], "News Scanner"),
    "agent_02": (STREAMS["market_data"], "Market Data"),
    "agent_03": (STREAMS["events"], "Events Engine"),
    "agent_04": (STREAMS["technicals"], "Momentum Bot"),
    "agent_05": (STREAMS["risk"], "Risk Guard"),
    "agent_06": (STREAMS["data_science"], "Data Scientist"),
    "agent_07": (STREAMS["smart_money"], "Smart Money"),
    "agent_08": (STREAMS["position_monitor"], "Position Monitor"),
}


@app.get("/agents/status")
async def get_agent_status(_user: str = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Get live status for all 7 agents from heartbeat stream + signal counts."""
    redis = bus.redis

    # Read recent heartbeats
    heartbeats = await redis.xrevrange(STREAMS["heartbeat"], count=100)
    latest: dict[str, dict[str, str]] = {}
    for _msg_id, data in heartbeats:
        aid = data.get("agent_id", "")
        if aid and aid not in latest:
            latest[aid] = data

    # Count signals per agent stream
    signal_counts: dict[str, int] = {}
    for aid, (stream, _name) in AGENT_STREAMS.items():
        try:
            signal_counts[aid] = await redis.xlen(stream)
        except Exception:
            signal_counts[aid] = 0

    # Build response
    now = datetime.utcnow()
    result = []
    for aid, (stream, name) in AGENT_STREAMS.items():
        hb = latest.get(aid, {})
        hb_ts = hb.get("timestamp", "")
        if hb_ts:
            try:
                delta = (now - datetime.fromisoformat(hb_ts)).total_seconds()
                last_hb = f"{int(delta)}s ago" if delta < 120 else f"{int(delta // 60)}m ago"
                status = "active" if delta < 90 else "idle"
            except ValueError:
                last_hb = "unknown"
                status = "idle"
        else:
            last_hb = "no heartbeat"
            status = "offline"

        result.append({
            "agent_id": aid,
            "agent_name": name,
            "status": status,
            "last_heartbeat": last_hb,
            "signal_count": signal_counts.get(aid, 0),
        })

    return result


@app.get("/agents/{agent_id}/feed")
async def get_agent_feed(
    agent_id: str,
    limit: int = 50,
    _user: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Get recent activity feed entries from an agent's signal stream."""
    if agent_id not in AGENT_STREAMS:
        raise HTTPException(404, f"Unknown agent: {agent_id}")

    stream, name = AGENT_STREAMS[agent_id]
    redis = bus.redis

    entries_raw = await redis.xrevrange(stream, count=limit)
    entries = []
    for msg_id, data in entries_raw:
        entries.append({"id": msg_id, "data": data})

    return {"agent_id": agent_id, "agent_name": name, "stream": stream, "entries": entries}


# ─── Entrypoint ───

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("quantum_edge.api:app", host="0.0.0.0", port=8001, reload=True)
