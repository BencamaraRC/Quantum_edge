"""Portfolio and position models — Agent 5 is sole writer."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Position(BaseModel):
    """A single open position (equity or options)."""

    symbol: str
    qty: int
    side: str  # long, short
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float
    cost_basis: float
    asset_class: str = "us_equity"  # us_equity, us_option
    exchange: str = ""


class OptionLeg(BaseModel):
    """A single leg of an options order."""

    symbol: str  # OCC symbol e.g. AAPL250321C00175000
    underlying: str  # e.g. AAPL
    expiration: str  # YYYY-MM-DD
    strike: float
    option_type: str  # call, put
    side: str  # buy_to_open, sell_to_open, buy_to_close, sell_to_close
    qty: int


class OptionQuote(BaseModel):
    """Option chain quote for a single contract."""

    symbol: str  # OCC symbol
    underlying: str
    expiration: str
    strike: float
    option_type: str  # call, put
    bid: float = 0.0
    ask: float = 0.0
    mid: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    implied_volatility: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


class OptionsPosition(BaseModel):
    """An open options position."""

    symbol: str  # OCC symbol
    underlying: str
    expiration: str
    strike: float
    option_type: str  # call, put
    qty: int
    side: str  # long, short
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    cost_basis: float
    # Greeks
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


class PortfolioState(BaseModel):
    """Full portfolio snapshot — written exclusively by Agent 5."""

    equity: float
    cash: float
    buying_power: float
    portfolio_value: float
    positions: list[Position] = Field(default_factory=list)
    options_positions: list[OptionsPosition] = Field(default_factory=list)
    open_orders: int = 0

    # Daily P&L tracking
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    daily_loss_limit: float = 0.0
    daily_loss_remaining: float = 0.0

    # Risk metrics
    total_exposure: float = 0.0
    total_exposure_pct: float = 0.0
    max_position_pct: float = 0.0
    largest_position_pct: float = 0.0
    correlated_exposure: dict[str, float] = Field(default_factory=dict)
    sector_exposure: dict[str, float] = Field(default_factory=dict)

    # Options Greeks (aggregate)
    portfolio_delta: float = 0.0
    portfolio_gamma: float = 0.0
    portfolio_theta: float = 0.0
    portfolio_vega: float = 0.0

    # Circuit breaker
    circuit_breaker_active: bool = False
    circuit_breaker_reason: str | None = None

    updated_at: datetime = Field(default_factory=datetime.utcnow)
    source: str = "alpaca"

    def position_for(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None

    def has_position(self, symbol: str) -> bool:
        return self.position_for(symbol) is not None

    def to_context_dict(self) -> dict[str, Any]:
        """Flatten for Redis Hash storage."""
        return {
            "equity": str(self.equity),
            "cash": str(self.cash),
            "buying_power": str(self.buying_power),
            "portfolio_value": str(self.portfolio_value),
            "daily_pnl": str(self.daily_pnl),
            "daily_pnl_pct": str(self.daily_pnl_pct),
            "daily_loss_remaining": str(self.daily_loss_remaining),
            "total_exposure_pct": str(self.total_exposure_pct),
            "open_positions": str(len(self.positions)),
            "circuit_breaker_active": str(self.circuit_breaker_active),
            "options_positions": str(len(self.options_positions)),
            "portfolio_delta": str(self.portfolio_delta),
            "portfolio_theta": str(self.portfolio_theta),
            "updated_at": self.updated_at.isoformat(),
        }
