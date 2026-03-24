"""Agent 5: Risk Guard — risk checks, Kelly sizing, VIX modulation, veto authority.

SOLE WRITER of portfolio state. Reads from Alpaca API every 30s.
Has absolute veto authority over all trades.

Strategy rules enforced:
- Max 3 open positions (Rule 3)
- R:R minimum 2.5:1 (Rule 5)
- VIX >= 30 circuit breaker (H7)
- VIX 18-25 Kelly reduction (H7)
- Conviction-tier Kelly multipliers (Score bands)
- 25% NAV max position cap
- Satellite 0.5x Kelly (Rule 7)
- Never average down (Rule 6 — bracket orders enforce this)

Publishes: qe:signals:risk
Updates context: qe:state:portfolio (single-writer principle)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from quantum_edge.broker.alpaca import AlpacaBroker
from quantum_edge.core.base_agent import BaseAgent
from quantum_edge.core.config import settings
from quantum_edge.core.message_bus import STREAMS
from quantum_edge.core.strategy import (
    MAX_OPEN_POSITIONS,
    MIN_RR_RATIO,
    SATELLITE_KELLY_FRACTION,
    VIX_CIRCUIT_BREAKER,
    VIX_KELLY_RANGE,
    kelly_multiplier_for_score,
)
from quantum_edge.models.events import PipelineEvent, PipelineEventType
from quantum_edge.models.memo import (
    Conviction,
    Direction,
    InvestmentMemo,
    MemoPhase,
    MemoScore,
    RiskCheckResult,
)
from quantum_edge.models.portfolio import PortfolioState

logger = logging.getLogger(__name__)


class RiskGuard(BaseAgent):
    agent_id = "agent_05"
    agent_name = "risk_guard"
    consumer_group = "cg:agent_05_risk_guard"
    subscribe_streams = [STREAMS["phase"], STREAMS["execution"]]
    cycle_seconds = 30.0

    def __init__(self) -> None:
        super().__init__()
        self._broker = AlpacaBroker()
        self._portfolio: PortfolioState | None = None
        self._current_vix: float = 15.0  # Updated each cycle
        self._portfolio_refresh_failures: int = 0
        self._last_portfolio_success: datetime | None = None

    async def on_start(self) -> None:
        await self._broker.connect()
        await self._refresh_portfolio()
        logger.info("Risk Guard agent started (max_positions=%d, min_rr=%.1f)",
                     MAX_OPEN_POSITIONS, MIN_RR_RATIO)

    async def on_stop(self) -> None:
        await self._broker.disconnect()

    async def on_cycle(self) -> None:
        """Refresh portfolio state, fetch VIX, update context."""
        await self._refresh_portfolio()
        await self._refresh_vix()

    async def on_message(self, stream: str, msg_id: str, data: dict[str, str]) -> None:
        """Handle risk check phase events."""
        if stream != STREAMS["phase"]:
            return
        if data.get("event_type", "") != "phase_advance":
            return

        import orjson
        try:
            event_data = orjson.loads(data.get("data", "{}"))
            if isinstance(event_data, str):
                event_data = orjson.loads(event_data)
            parsed_data = event_data.get("data", event_data)
            to_phase = parsed_data.get("to_phase", "")
        except Exception:
            return

        if to_phase != "risk_check":
            return

        symbol = data.get("symbol", "")
        memo_id = data.get("memo_id", "")
        if not symbol or not memo_id:
            return

        entry_price = float(parsed_data.get("entry_price", "0"))
        stop_loss = float(parsed_data.get("stop_loss", "0"))
        take_profit = float(parsed_data.get("take_profit", "0"))

        if entry_price <= 0:
            logger.warning("Risk check skipped — invalid entry price for %s", symbol)
            return

        result = await self.evaluate_risk(
            memo=self._build_stub_memo(symbol, parsed_data),
            position_entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        from uuid import UUID
        await self.publish_event(PipelineEvent(
            event_type=PipelineEventType.RISK_CHECK_COMPLETE,
            memo_id=UUID(memo_id),
            symbol=symbol,
            agent_id=self.agent_id,
            data={
                "approved": result.approved,
                "veto_reason": result.veto_reason or "",
                "position_size_shares": str(result.position_size_shares),
                "position_size_dollars": str(result.position_size_dollars),
                "kelly_fraction": str(result.kelly_fraction),
            },
        ))
        logger.info("Risk check for %s: approved=%s", symbol, result.approved)

    def _build_stub_memo(self, symbol: str, event_data: dict) -> InvestmentMemo:
        """Build a minimal InvestmentMemo for risk evaluation from event data."""
        from uuid import uuid4

        direction_str = event_data.get("direction", "long")
        direction = Direction.LONG if direction_str == "long" else Direction.SHORT
        is_satellite = event_data.get("is_satellite", False)

        memo = InvestmentMemo(
            memo_id=uuid4(),
            symbol=symbol,
            version=2,
            phase=MemoPhase.RISK_CHECK,
            is_satellite=bool(is_satellite),
        )
        memo.pass2_score = MemoScore(
            composite_score=float(event_data.get("composite_score", "0.7")),
            direction=direction,
            conviction=Conviction(event_data.get("conviction", "high")),
            threshold=0.75,
            passed=True,
        )
        return memo

    async def _refresh_portfolio(self) -> None:
        """Read portfolio from Alpaca and write to context layer."""
        try:
            new_portfolio = await self._broker.get_portfolio_state()
            self._portfolio = new_portfolio
            self._portfolio_refresh_failures = 0
            self._last_portfolio_success = datetime.utcnow()

            # Check daily P&L circuit breaker
            if self._portfolio.daily_pnl_pct <= -settings.max_daily_loss_pct:
                if not self._portfolio.circuit_breaker_active:
                    self._portfolio.circuit_breaker_active = True
                    self._portfolio.circuit_breaker_reason = (
                        f"Daily loss limit hit: {self._portfolio.daily_pnl_pct:.2f}%"
                    )
                    logger.critical(
                        "CIRCUIT BREAKER TRIGGERED (P&L): %s",
                        self._portfolio.circuit_breaker_reason,
                    )
                    await self._broker.cancel_all_orders()
                    await self._broker.close_all_positions()

            # Write portfolio context (single-writer principle)
            await self.update_context("portfolio", self._portfolio.to_context_dict())

        except Exception:
            self._portfolio_refresh_failures += 1
            if self._portfolio_refresh_failures >= 3:
                logger.critical(
                    "Portfolio refresh failed %d consecutive times — portfolio state is stale (last success: %s)",
                    self._portfolio_refresh_failures,
                    self._last_portfolio_success.isoformat() if self._last_portfolio_success else "never",
                )
            else:
                logger.exception("Portfolio refresh failed")

    async def _refresh_vix(self) -> None:
        """Fetch current VIX level for Kelly modulation and circuit breaker."""
        try:
            from alpaca.data.requests import StockLatestQuoteRequest
            from alpaca.data.historical import StockHistoricalDataClient

            client = StockHistoricalDataClient(
                api_key=settings.alpaca_api_key,
                secret_key=settings.alpaca_secret_key,
            )
            # Use VIXY as VIX proxy (Alpaca doesn't provide ^VIX directly)
            request = StockLatestQuoteRequest(symbol_or_symbols=["VIXY"])
            quotes = client.get_stock_latest_quote(request)
            vixy_quote = quotes.get("VIXY")
            if vixy_quote:
                # VIXY roughly tracks VIX — use as proxy
                vixy_price = float(vixy_quote.ask_price + vixy_quote.bid_price) / 2
                # Approximate VIX from VIXY (rough mapping)
                self._current_vix = max(10.0, vixy_price * 1.5)
            else:
                self._current_vix = 15.0  # Default calm

            # VIX circuit breaker (H7)
            if self._current_vix >= VIX_CIRCUIT_BREAKER:
                if self._portfolio and not self._portfolio.circuit_breaker_active:
                    self._portfolio.circuit_breaker_active = True
                    self._portfolio.circuit_breaker_reason = (
                        f"VIX circuit breaker: {self._current_vix:.1f} >= {VIX_CIRCUIT_BREAKER}"
                    )
                    logger.critical(
                        "CIRCUIT BREAKER TRIGGERED (VIX): %s",
                        self._portfolio.circuit_breaker_reason,
                    )
                    await self._broker.cancel_all_orders()
                    await self._broker.close_all_positions()
                    await self.update_context("portfolio", self._portfolio.to_context_dict())

        except Exception:
            logger.debug("VIX refresh failed, using default")
            self._current_vix = 15.0

    async def evaluate_risk(
        self,
        memo: InvestmentMemo,
        position_entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> RiskCheckResult:
        """Run all risk checks and compute Kelly sizing."""
        if self._portfolio is None:
            return RiskCheckResult(approved=False, veto_reason="Portfolio state unavailable")

        checks: dict[str, bool] = {}
        veto_reason: str | None = None

        # 1. Circuit breaker check (daily P&L + VIX)
        checks["circuit_breaker"] = not self._portfolio.circuit_breaker_active
        if self._portfolio.circuit_breaker_active:
            veto_reason = f"Circuit breaker active: {self._portfolio.circuit_breaker_reason}"

        # 2. VIX circuit breaker (redundant but explicit)
        checks["vix_level"] = self._current_vix < VIX_CIRCUIT_BREAKER
        if not checks["vix_level"]:
            veto_reason = veto_reason or f"VIX {self._current_vix:.1f} >= {VIX_CIRCUIT_BREAKER} circuit breaker"

        # 3. Daily loss limit
        remaining = self._portfolio.daily_loss_limit + self._portfolio.daily_pnl
        checks["daily_loss_limit"] = remaining > 0
        if not checks["daily_loss_limit"]:
            veto_reason = veto_reason or "Daily loss limit exhausted"

        # 4. Max position size
        equity = self._portfolio.equity
        max_position_value = equity * (settings.max_kelly_pct / 100)
        checks["max_position_size"] = True  # Checked during sizing

        # 5. Correlated exposure
        symbol = memo.symbol
        sector = self._get_sector(symbol)
        sector_exposure = self._portfolio.sector_exposure.get(sector, 0)
        checks["correlated_exposure"] = sector_exposure < (settings.max_correlated_exposure_pct / 100 * equity)
        if not checks["correlated_exposure"]:
            veto_reason = veto_reason or f"Sector {sector} exposure too high"

        # 6. Buying power
        checks["buying_power"] = self._portfolio.buying_power > 0
        if not checks["buying_power"]:
            veto_reason = veto_reason or "Insufficient buying power"

        # 7. Risk-reward ratio (Rule 5: minimum 2.5:1)
        direction = memo.pass2_score.direction if memo.pass2_score else Direction.LONG
        if direction == Direction.LONG:
            risk = position_entry_price - stop_loss
            reward = take_profit - position_entry_price
        else:
            risk = stop_loss - position_entry_price
            reward = position_entry_price - take_profit
        rr_ratio = reward / risk if risk > 0 else 0
        checks["risk_reward"] = rr_ratio >= MIN_RR_RATIO
        if not checks["risk_reward"]:
            veto_reason = veto_reason or f"Risk/reward {rr_ratio:.2f} below {MIN_RR_RATIO}"

        # 8. Not already in position (Rule 6: never average down)
        checks["no_duplicate_position"] = not self._portfolio.has_position(symbol)
        if not checks["no_duplicate_position"]:
            veto_reason = veto_reason or f"Already in position: {symbol} (Rule 6: never average down)"

        # 9. Market hours
        try:
            market_open = await self._broker.is_market_open()
            checks["market_open"] = market_open
            if not market_open:
                veto_reason = veto_reason or "Market closed"
        except Exception:
            checks["market_open"] = False
            veto_reason = veto_reason or "Cannot verify market hours"

        # 10. Max open positions (Rule 3: max 3)
        checks["max_positions"] = len(self._portfolio.positions) < MAX_OPEN_POSITIONS
        if not checks["max_positions"]:
            veto_reason = veto_reason or f"Max positions reached ({MAX_OPEN_POSITIONS})"

        # 11. Conviction threshold
        conviction_ok = memo.pass2_score is not None and memo.pass2_score.conviction.value in ("high", "very_high")
        checks["conviction"] = conviction_ok
        if not conviction_ok:
            veto_reason = veto_reason or "Conviction too low for execution"

        # ─── Options-specific risk checks ───

        # 12. Portfolio delta exposure
        checks["delta_exposure"] = abs(self._portfolio.portfolio_delta) < settings.max_portfolio_delta
        if not checks["delta_exposure"]:
            veto_reason = veto_reason or f"Portfolio delta {self._portfolio.portfolio_delta:.0f} exceeds limit"

        # 13. Daily theta decay
        checks["theta_decay"] = abs(self._portfolio.portfolio_theta) < settings.max_daily_theta_decay
        if not checks["theta_decay"]:
            veto_reason = veto_reason or f"Portfolio theta {self._portfolio.portfolio_theta:.0f} exceeds limit"

        # 14. No naked short options
        if not settings.allow_naked_shorts:
            has_naked = any(
                op.side == "short"
                for op in self._portfolio.options_positions
                if not self._is_covered(op)
            )
            checks["no_naked_shorts"] = not has_naked
            if not checks["no_naked_shorts"]:
                veto_reason = veto_reason or "Naked short options not allowed"

        # 15. Max contracts per position
        checks["max_contracts"] = all(
            op.qty <= settings.max_contracts_per_position
            for op in self._portfolio.options_positions
        )
        if not checks["max_contracts"]:
            veto_reason = veto_reason or f"Options position exceeds {settings.max_contracts_per_position} contracts"

        # ─── Kelly Criterion sizing with strategy modifiers ───
        kelly_fraction = self._compute_kelly(memo)
        position_value = min(
            equity * kelly_fraction,
            max_position_value,
            self._portfolio.buying_power * 0.95,
        )
        shares = int(position_value / position_entry_price) if position_entry_price > 0 else 0

        all_passed = all(checks.values())
        if not all_passed and veto_reason is None:
            failed = [k for k, v in checks.items() if not v]
            veto_reason = f"Failed checks: {', '.join(failed)}"

        return RiskCheckResult(
            approved=all_passed,
            veto_reason=veto_reason,
            position_size_shares=shares,
            position_size_dollars=position_value,
            kelly_fraction=kelly_fraction,
            risk_checks=checks,
            daily_loss_remaining=remaining,
            buying_power_available=self._portfolio.buying_power,
            max_position_pct=settings.max_kelly_pct,
            timestamp=datetime.utcnow(),
        )

    def _compute_kelly(self, memo: InvestmentMemo) -> float:
        """Compute Kelly fraction with strategy modifiers.

        Base: half-Kelly from win probability and R:R ratio.
        Modifiers:
        1. Score band multiplier (1.0x / 1.5x / 2.0x)
        2. VIX Kelly reduction (18-25 range)
        3. Satellite 0.5x fraction
        Cap: max_kelly_pct (25%) of NAV.
        """
        score = memo.pass2_score
        if score is None:
            return 0.01

        # Estimate win probability from composite score
        win_prob = min(0.7, max(0.3, score.composite_score))

        # Risk/reward from technical evaluation
        tech = memo.technical_eval
        rr_ratio = tech.risk_reward_ratio if tech else MIN_RR_RATIO

        # Base Kelly
        kelly = win_prob - (1 - win_prob) / rr_ratio
        kelly = max(0.01, kelly / 2)  # Half-Kelly for safety

        # 1. Score band multiplier
        multiplier = kelly_multiplier_for_score(score.composite_score)
        kelly *= multiplier

        # 2. VIX Kelly reduction (H7)
        vix_start, vix_end = VIX_KELLY_RANGE
        if self._current_vix >= vix_end:
            kelly *= 0.5
        elif self._current_vix >= vix_start:
            reduction = 1.0 - (self._current_vix - vix_start) / (vix_end - vix_start) * 0.5
            kelly *= reduction

        # 3. Satellite fraction (Rule 7: satellites at 0.5x Kelly)
        if memo.is_satellite:
            kelly *= SATELLITE_KELLY_FRACTION

        # Cap at max_kelly_pct of NAV
        kelly = min(settings.max_kelly_pct / 100, kelly)

        return kelly

    def _is_covered(self, op: Any) -> bool:
        """Check if a short option is covered by an offsetting position."""
        if self._portfolio is None:
            return False
        if op.option_type == "call":
            return self._portfolio.has_position(op.underlying)
        if op.option_type == "put":
            return any(
                other.underlying == op.underlying
                and other.option_type == "put"
                and other.side == "long"
                and other.expiration == op.expiration
                for other in self._portfolio.options_positions
                if other.symbol != op.symbol
            )
        return False

    def _get_sector(self, symbol: str) -> str:
        """Sector mapping for correlated exposure checks."""
        tech = {"AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMD", "AVGO", "TSM",
                "ADBE", "ORCL", "WDAY", "CRWD", "SNOW", "DDOG", "CRM", "NOW"}
        semis = {"SMCI", "AMD", "AVGO", "TSM"}
        finance = {"JPM", "BAC", "GS"}
        ev = {"TSLA", "RIVN", "NIO"}
        crypto = {"COIN"}
        ad_tech = {"TTD", "PUBM", "MGNI"}
        social = {"SNAP", "PINS", "RDDT"}
        infra = {"PWR", "FIX"}
        ecommerce = {"SHOP", "PANW", "AMZN"}

        if symbol in semis:
            return "semiconductors"
        if symbol in ad_tech:
            return "ad_tech"
        if symbol in social:
            return "social_media"
        if symbol in infra:
            return "infrastructure"
        if symbol in tech:
            return "technology"
        if symbol in finance:
            return "finance"
        if symbol in ev:
            return "ev"
        if symbol in crypto:
            return "crypto"
        if symbol in ecommerce:
            return "ecommerce"
        return "other"


async def main() -> None:
    from quantum_edge.utils.logging import setup_logging

    setup_logging()
    agent = RiskGuard()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
