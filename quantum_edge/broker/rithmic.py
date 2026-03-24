"""Rithmic stub — Phase 3 implementation."""

from __future__ import annotations

from typing import Any

from quantum_edge.broker.base import BrokerInterface
from quantum_edge.models.memo import ExecutionResult
from quantum_edge.models.portfolio import OptionLeg, OptionQuote, OptionsPosition, PortfolioState, Position


class RithmicBroker(BrokerInterface):
    """Placeholder for Rithmic implementation."""

    async def connect(self) -> None:
        raise NotImplementedError("Rithmic broker not yet implemented")

    async def disconnect(self) -> None:
        pass

    async def get_account(self) -> dict[str, Any]:
        raise NotImplementedError

    async def get_positions(self) -> list[Position]:
        raise NotImplementedError

    async def get_portfolio_state(self) -> PortfolioState:
        raise NotImplementedError

    async def submit_bracket_order(self, symbol: str, side: str, qty: int, entry_price: float | None, stop_loss: float, take_profit: float) -> ExecutionResult:
        raise NotImplementedError

    async def cancel_all_orders(self) -> int:
        raise NotImplementedError

    async def close_all_positions(self) -> int:
        raise NotImplementedError

    async def close_position(self, symbol: str) -> ExecutionResult:
        raise NotImplementedError

    async def is_market_open(self) -> bool:
        raise NotImplementedError

    async def get_option_chain(self, underlying: str, expiration: str | None = None) -> list[OptionQuote]:
        raise NotImplementedError

    async def get_options_positions(self) -> list[OptionsPosition]:
        raise NotImplementedError

    async def submit_options_order(self, symbol: str, option_type: str, expiration: str, strike: float, side: str, qty: int) -> ExecutionResult:
        raise NotImplementedError

    async def submit_spread_order(self, legs: list[OptionLeg]) -> ExecutionResult:
        raise NotImplementedError
