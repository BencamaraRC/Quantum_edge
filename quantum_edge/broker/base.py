"""Abstract broker interface for order execution."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from quantum_edge.models.memo import ExecutionResult
from quantum_edge.models.portfolio import (
    OptionLeg,
    OptionQuote,
    OptionsPosition,
    PortfolioState,
    Position,
)


class BrokerInterface(ABC):
    """Abstract base for broker implementations (Alpaca, IBKR, Rithmic)."""

    # ─── Connection ───

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection."""

    # ─── Account & Portfolio ───

    @abstractmethod
    async def get_account(self) -> dict[str, Any]:
        """Get account info (equity, buying power, etc.)."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get all open equity positions."""

    @abstractmethod
    async def get_portfolio_state(self) -> PortfolioState:
        """Get full portfolio snapshot."""

    # ─── Equity Orders ───

    @abstractmethod
    async def submit_bracket_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        entry_price: float | None,
        stop_loss: float,
        take_profit: float,
    ) -> ExecutionResult:
        """Submit a bracket order (entry + stop loss + take profit)."""

    @abstractmethod
    async def cancel_all_orders(self) -> int:
        """Cancel all open orders. Returns count cancelled."""

    @abstractmethod
    async def close_all_positions(self) -> int:
        """Close all open positions. Returns count closed."""

    @abstractmethod
    async def close_position(self, symbol: str) -> ExecutionResult:
        """Close a specific position."""

    @abstractmethod
    async def is_market_open(self) -> bool:
        """Check if the market is currently open."""

    # ─── Options ───

    @abstractmethod
    async def get_option_chain(
        self,
        underlying: str,
        expiration: str | None = None,
    ) -> list[OptionQuote]:
        """Get option chain for an underlying symbol."""

    @abstractmethod
    async def get_options_positions(self) -> list[OptionsPosition]:
        """Get all open options positions."""

    @abstractmethod
    async def submit_options_order(
        self,
        symbol: str,
        option_type: str,
        expiration: str,
        strike: float,
        side: str,
        qty: int,
    ) -> ExecutionResult:
        """Submit a single-leg options order."""

    @abstractmethod
    async def submit_spread_order(
        self,
        legs: list[OptionLeg],
    ) -> ExecutionResult:
        """Submit a multi-leg spread order (vertical, iron condor, etc.)."""

    # ─── Position Management ───

    @abstractmethod
    async def get_order_by_id(self, order_id: str) -> dict[str, Any]:
        """Get order details including child legs for bracket orders."""

    @abstractmethod
    async def cancel_order_by_id(self, order_id: str) -> bool:
        """Cancel a specific order by ID. Returns True on success."""

    @abstractmethod
    async def submit_trailing_stop_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        trail_percent: float,
    ) -> ExecutionResult:
        """Submit a trailing stop order. Side is the closing side (sell for long, buy for short)."""

    @abstractmethod
    async def get_open_position(self, symbol: str) -> Position | None:
        """Get a single open position by symbol, or None if not found."""
