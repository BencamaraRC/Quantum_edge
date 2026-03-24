"""Alpaca Trading API broker implementation — equities + options."""

from __future__ import annotations

import asyncio
import functools
import logging
from datetime import datetime
from typing import Any, Callable, TypeVar

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
    StopLossRequest,
    TakeProfitRequest,
    TrailingStopOrderRequest,
)
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from quantum_edge.broker.base import BrokerInterface
from quantum_edge.core.config import settings
from quantum_edge.models.memo import ExecutionResult
from quantum_edge.models.portfolio import (
    OptionLeg,
    OptionQuote,
    OptionsPosition,
    PortfolioState,
    Position,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Retry decorator for Alpaca API calls
_api_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
    reraise=True,
)


class AlpacaBroker(BrokerInterface):
    """Alpaca Trading API implementation with bracket orders + options."""

    def __init__(self) -> None:
        self._client: TradingClient | None = None

    async def connect(self) -> None:
        self._client = TradingClient(
            api_key=settings.alpaca_api_key,
            secret_key=settings.alpaca_secret_key,
            paper=True,  # Always paper trading for safety
        )
        logger.info("Connected to Alpaca (paper mode)")

    async def disconnect(self) -> None:
        if self._client is not None:
            # Close the underlying requests session if present
            session = getattr(self._client, "_session", None)
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass
        self._client = None

    @property
    def client(self) -> TradingClient:
        if self._client is None:
            raise RuntimeError("AlpacaBroker not connected.")
        return self._client

    async def _call_api(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run a sync Alpaca SDK call in an executor with retry logic."""
        loop = asyncio.get_running_loop()

        @_api_retry
        def _do_call() -> T:
            return func(*args, **kwargs)

        return await loop.run_in_executor(None, _do_call)

    # ─── Account & Portfolio ───

    async def get_account(self) -> dict[str, Any]:
        account = await self._call_api(self.client.get_account)
        return {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "currency": account.currency,
            "status": account.status.value if account.status else "unknown",
        }

    async def get_positions(self) -> list[Position]:
        positions = await self._call_api(self.client.get_all_positions)
        return [
            Position(
                symbol=p.symbol,
                qty=int(p.qty),
                side="long" if int(p.qty) > 0 else "short",
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
                unrealized_pl_pct=float(p.unrealized_plpc),
                cost_basis=float(p.cost_basis),
                asset_class=str(getattr(p, "asset_class", "us_equity")),
                exchange=p.exchange.value if p.exchange else "",
            )
            for p in positions
            if str(getattr(p, "asset_class", "us_equity")) != "us_option"
        ]

    async def get_options_positions(self) -> list[OptionsPosition]:
        """Get all open options positions from Alpaca."""
        positions = await self._call_api(self.client.get_all_positions)
        options: list[OptionsPosition] = []
        for p in positions:
            if str(getattr(p, "asset_class", "")) != "us_option":
                continue
            # Parse OCC symbol: AAPL250321C00175000
            occ = p.symbol
            underlying = self._parse_occ_underlying(occ)
            expiration = self._parse_occ_expiration(occ)
            strike = self._parse_occ_strike(occ)
            opt_type = self._parse_occ_type(occ)

            options.append(
                OptionsPosition(
                    symbol=occ,
                    underlying=underlying,
                    expiration=expiration,
                    strike=strike,
                    option_type=opt_type,
                    qty=abs(int(p.qty)),
                    side="long" if int(p.qty) > 0 else "short",
                    avg_entry_price=float(p.avg_entry_price),
                    current_price=float(p.current_price),
                    market_value=float(p.market_value),
                    unrealized_pl=float(p.unrealized_pl),
                    cost_basis=float(p.cost_basis),
                )
            )
        return options

    async def get_portfolio_state(self) -> PortfolioState:
        account_data = await self.get_account()
        positions = await self.get_positions()
        options_positions = await self.get_options_positions()

        equity = account_data["equity"]
        equity_exposure = sum(abs(p.market_value) for p in positions)
        options_exposure = sum(abs(op.market_value) for op in options_positions)
        total_exposure = equity_exposure + options_exposure
        daily_loss_limit = equity * (settings.max_daily_loss_pct / 100.0)

        # Aggregate options Greeks
        portfolio_delta = sum(op.delta * op.qty * (1 if op.side == "long" else -1) for op in options_positions)
        portfolio_gamma = sum(op.gamma * op.qty for op in options_positions)
        portfolio_theta = sum(op.theta * op.qty * (1 if op.side == "long" else -1) for op in options_positions)
        portfolio_vega = sum(op.vega * op.qty for op in options_positions)

        return PortfolioState(
            equity=equity,
            cash=account_data["cash"],
            buying_power=account_data["buying_power"],
            portfolio_value=account_data["portfolio_value"],
            positions=positions,
            options_positions=options_positions,
            total_exposure=total_exposure,
            total_exposure_pct=(total_exposure / equity * 100) if equity > 0 else 0,
            largest_position_pct=(
                max((abs(p.market_value) / equity * 100) for p in positions)
                if positions
                else 0
            ),
            daily_loss_limit=daily_loss_limit,
            portfolio_delta=portfolio_delta,
            portfolio_gamma=portfolio_gamma,
            portfolio_theta=portfolio_theta,
            portfolio_vega=portfolio_vega,
            updated_at=datetime.utcnow(),
        )

    # ─── Equity Orders ───

    async def submit_bracket_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        entry_price: float | None,
        stop_loss: float,
        take_profit: float,
    ) -> ExecutionResult:
        try:
            order_side = OrderSide.BUY if side == "long" else OrderSide.SELL

            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                order_class="bracket",
                stop_loss=StopLossRequest(stop_price=stop_loss),
                take_profit=TakeProfitRequest(limit_price=take_profit),
            )

            order = await self._call_api(self.client.submit_order, order_request)

            result = ExecutionResult(
                order_id=str(order.id),
                broker="alpaca",
                symbol=symbol,
                side=side,
                qty=qty,
                order_type="bracket",
                entry_price=entry_price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                status=order.status.value if order.status else "submitted",
            )

            logger.info(
                "Bracket order submitted: %s %s %d @ %s (SL=%s TP=%s)",
                side, symbol, qty, entry_price or "market", stop_loss, take_profit,
            )
            return result

        except Exception as e:
            logger.error("Order submission failed: %s", e)
            return ExecutionResult(
                broker="alpaca", symbol=symbol, side=side, qty=qty,
                status="failed", error=str(e),
            )

    async def cancel_all_orders(self) -> int:
        cancelled = await self._call_api(self.client.cancel_orders)
        count = len(cancelled) if cancelled else 0
        logger.warning("Cancelled %d orders", count)
        return count

    async def close_all_positions(self) -> int:
        closed = await self._call_api(self.client.close_all_positions, cancel_orders=True)
        count = len(closed) if closed else 0
        logger.warning("Closed %d positions", count)
        return count

    async def close_position(self, symbol: str) -> ExecutionResult:
        try:
            order = await self._call_api(self.client.close_position, symbol)
            return ExecutionResult(
                order_id=str(order.id) if hasattr(order, "id") else "",
                broker="alpaca", symbol=symbol, status="closing",
            )
        except Exception as e:
            return ExecutionResult(
                broker="alpaca", symbol=symbol, status="failed", error=str(e),
            )

    async def is_market_open(self) -> bool:
        clock = await self._call_api(self.client.get_clock)
        return clock.is_open

    # ─── Position Management ───

    async def get_order_by_id(self, order_id: str) -> dict[str, Any]:
        """Get order details including child legs for bracket orders."""
        order = await self._call_api(self.client.get_order_by_id, order_id)
        result: dict[str, Any] = {
            "id": str(order.id),
            "status": order.status.value if order.status else "unknown",
            "symbol": order.symbol,
            "side": order.side.value if order.side else "",
            "qty": str(order.qty),
            "legs": [],
        }
        if hasattr(order, "legs") and order.legs:
            for leg in order.legs:
                result["legs"].append({
                    "id": str(leg.id),
                    "order_type": leg.order_type.value if leg.order_type else "",
                    "status": leg.status.value if leg.status else "",
                    "stop_price": str(getattr(leg, "stop_price", "")),
                    "limit_price": str(getattr(leg, "limit_price", "")),
                })
        return result

    async def cancel_order_by_id(self, order_id: str) -> bool:
        """Cancel a specific order by ID."""
        try:
            await self._call_api(self.client.cancel_order_by_id, order_id)
            logger.info("Cancelled order: %s", order_id)
            return True
        except Exception as e:
            logger.error("Failed to cancel order %s: %s", order_id, e)
            return False

    async def submit_trailing_stop_order(
        self,
        symbol: str,
        side: str,
        qty: int,
        trail_percent: float,
    ) -> ExecutionResult:
        """Submit a native Alpaca trailing stop order."""
        try:
            order_side = OrderSide.SELL if side == "long" else OrderSide.BUY
            order_request = TrailingStopOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                trail_percent=trail_percent,
            )
            order = await self._call_api(self.client.submit_order, order_request)
            logger.info(
                "Trailing stop submitted: %s %s %d shares, trail=%.1f%%",
                side, symbol, qty, trail_percent,
            )
            return ExecutionResult(
                order_id=str(order.id),
                broker="alpaca",
                symbol=symbol,
                side=side,
                qty=qty,
                order_type="trailing_stop",
                status=order.status.value if order.status else "submitted",
            )
        except Exception as e:
            logger.error("Trailing stop submission failed: %s", e)
            return ExecutionResult(
                broker="alpaca", symbol=symbol, side=side, qty=qty,
                order_type="trailing_stop", status="failed", error=str(e),
            )

    async def get_open_position(self, symbol: str) -> Position | None:
        """Get a single open position by symbol."""
        try:
            p = await self._call_api(self.client.get_open_position, symbol)
            return Position(
                symbol=p.symbol,
                qty=int(p.qty),
                side="long" if int(p.qty) > 0 else "short",
                avg_entry_price=float(p.avg_entry_price),
                current_price=float(p.current_price),
                market_value=float(p.market_value),
                unrealized_pl=float(p.unrealized_pl),
                unrealized_pl_pct=float(p.unrealized_plpc),
                cost_basis=float(p.cost_basis),
                asset_class=str(getattr(p, "asset_class", "us_equity")),
                exchange=p.exchange.value if p.exchange else "",
            )
        except Exception:
            return None

    # ─── Options ───

    async def get_option_chain(
        self,
        underlying: str,
        expiration: str | None = None,
    ) -> list[OptionQuote]:
        """Get option chain via Alpaca Options API."""
        try:
            from alpaca.data.historical.option import OptionHistoricalDataClient
            from alpaca.data.requests import OptionChainRequest

            data_client = OptionHistoricalDataClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
            )

            params: dict[str, Any] = {"underlying_symbol": underlying}
            if expiration:
                params["expiration_date"] = expiration

            request = OptionChainRequest(**params)
            chain = data_client.get_option_chain(request)

            quotes: list[OptionQuote] = []
            for occ_symbol, snapshots in chain.items():
                snapshot = snapshots if not isinstance(snapshots, list) else snapshots[-1]
                quote_data = getattr(snapshot, "latest_quote", None)
                greeks = getattr(snapshot, "greeks", None)

                quotes.append(
                    OptionQuote(
                        symbol=occ_symbol,
                        underlying=underlying,
                        expiration=self._parse_occ_expiration(occ_symbol),
                        strike=self._parse_occ_strike(occ_symbol),
                        option_type=self._parse_occ_type(occ_symbol),
                        bid=float(getattr(quote_data, "bid_price", 0)),
                        ask=float(getattr(quote_data, "ask_price", 0)),
                        mid=(float(getattr(quote_data, "bid_price", 0)) + float(getattr(quote_data, "ask_price", 0))) / 2,
                        volume=int(getattr(snapshot, "daily_bar", {}).get("volume", 0) if isinstance(getattr(snapshot, "daily_bar", None), dict) else 0),
                        open_interest=int(getattr(snapshot, "open_interest", 0)),
                        implied_volatility=float(getattr(greeks, "implied_volatility", 0) if greeks else 0),
                        delta=float(getattr(greeks, "delta", 0) if greeks else 0),
                        gamma=float(getattr(greeks, "gamma", 0) if greeks else 0),
                        theta=float(getattr(greeks, "theta", 0) if greeks else 0),
                        vega=float(getattr(greeks, "vega", 0) if greeks else 0),
                    )
                )
            return quotes

        except Exception as e:
            logger.error("Failed to get option chain for %s: %s", underlying, e)
            return []

    async def submit_options_order(
        self,
        symbol: str,
        option_type: str,
        expiration: str,
        strike: float,
        side: str,
        qty: int,
    ) -> ExecutionResult:
        """Submit a single-leg options order via Alpaca unified API."""
        try:
            # Build OCC symbol if not already one
            occ_symbol = symbol if len(symbol) > 10 else self._build_occ_symbol(
                symbol, expiration, strike, option_type
            )

            order_side = OrderSide.BUY if "buy" in side.lower() else OrderSide.SELL

            order_request = MarketOrderRequest(
                symbol=occ_symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )

            order = await self._call_api(self.client.submit_order, order_request)

            result = ExecutionResult(
                order_id=str(order.id),
                broker="alpaca",
                symbol=occ_symbol,
                side=side,
                qty=qty,
                order_type="options_single",
                status=order.status.value if order.status else "submitted",
            )

            logger.info(
                "Options order submitted: %s %s %d contracts",
                side, occ_symbol, qty,
            )
            return result

        except Exception as e:
            logger.error("Options order failed: %s", e)
            return ExecutionResult(
                broker="alpaca", symbol=symbol, side=side, qty=qty,
                order_type="options_single", status="failed", error=str(e),
            )

    async def submit_spread_order(
        self,
        legs: list[OptionLeg],
    ) -> ExecutionResult:
        """Submit a multi-leg options spread via Alpaca."""
        try:
            # Alpaca supports multi-leg via their options order endpoint
            # For now, submit legs sequentially (Alpaca multi-leg API varies by plan)
            results: list[ExecutionResult] = []
            for leg in legs:
                occ_symbol = self._build_occ_symbol(
                    leg.underlying, leg.expiration, leg.strike, leg.option_type
                )
                result = await self.submit_options_order(
                    symbol=occ_symbol,
                    option_type=leg.option_type,
                    expiration=leg.expiration,
                    strike=leg.strike,
                    side=leg.side,
                    qty=leg.qty,
                )
                results.append(result)

            # Return combined result
            all_ok = all(r.status != "failed" for r in results)
            order_ids = ",".join(r.order_id for r in results if r.order_id)

            return ExecutionResult(
                order_id=order_ids,
                broker="alpaca",
                symbol=legs[0].underlying if legs else "",
                side="spread",
                qty=legs[0].qty if legs else 0,
                order_type="options_spread",
                status="submitted" if all_ok else "partial_failure",
                error="; ".join(r.error for r in results if r.error) or None,
            )

        except Exception as e:
            logger.error("Spread order failed: %s", e)
            return ExecutionResult(
                broker="alpaca", symbol=legs[0].underlying if legs else "",
                side="spread", qty=0, order_type="options_spread",
                status="failed", error=str(e),
            )

    # ─── OCC Symbol Helpers ───

    @staticmethod
    def _build_occ_symbol(
        underlying: str, expiration: str, strike: float, option_type: str,
    ) -> str:
        """Build OCC-format option symbol: AAPL250321C00175000."""
        exp = expiration.replace("-", "")  # YYYYMMDD → YYMMDD
        if len(exp) == 8:
            exp = exp[2:]  # Strip century
        opt_char = "C" if option_type.lower() == "call" else "P"
        strike_int = int(strike * 1000)
        return f"{underlying:<6}{exp}{opt_char}{strike_int:08d}"

    @staticmethod
    def _parse_occ_underlying(occ: str) -> str:
        return occ[:6].rstrip() if len(occ) > 15 else occ

    @staticmethod
    def _parse_occ_expiration(occ: str) -> str:
        if len(occ) > 15:
            date_part = occ[6:12]
            return f"20{date_part[:2]}-{date_part[2:4]}-{date_part[4:6]}"
        return ""

    @staticmethod
    def _parse_occ_strike(occ: str) -> float:
        if len(occ) > 15:
            return int(occ[13:]) / 1000.0
        return 0.0

    @staticmethod
    def _parse_occ_type(occ: str) -> str:
        if len(occ) > 12:
            return "call" if occ[12] == "C" else "put"
        return "unknown"
