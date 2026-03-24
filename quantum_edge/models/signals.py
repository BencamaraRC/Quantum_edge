"""Signal type definitions for agent inter-communication."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SignalType(StrEnum):
    NEWS_SENTIMENT = "news_sentiment"
    MARKET_DATA = "market_data"
    EVENT_CALENDAR = "event_calendar"
    TECHNICAL = "technical"
    SMART_MONEY = "smart_money"
    REGIME = "regime"
    RISK = "risk"


class NewsSignal(BaseModel):
    """Output from Agent 1: News Scanner."""

    symbol: str
    headline: str
    source: str
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    sentiment_label: str  # positive, negative, neutral
    relevance_score: float = Field(ge=0.0, le=1.0)
    finbert_confidence: float = Field(ge=0.0, le=1.0)
    published_at: datetime
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    url: str = ""
    dedup_hash: str = ""


class MarketDataSignal(BaseModel):
    """Output from Agent 2: Market Data."""

    symbol: str
    price: float
    volume: int
    vwap: float
    bid: float
    ask: float
    spread: float
    daily_high: float
    daily_low: float
    daily_open: float
    prev_close: float
    change_pct: float
    relative_volume: float  # vs 20-day avg
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    bar_data: dict[str, Any] = Field(default_factory=dict)


class EventSignal(BaseModel):
    """Output from Agent 3: Events Engine."""

    symbol: str
    event_type: str  # earnings, fda_decision, fomc, economic_release, etc.
    event_name: str
    event_time: datetime
    impact_level: str  # high, medium, low
    days_until: float
    historical_reaction: dict[str, Any] = Field(default_factory=dict)
    fingerprint_match: float = Field(ge=0.0, le=1.0, default=0.0)
    avoid_entry: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RegimeSignal(BaseModel):
    """Output from Agent 6: Data Scientist (regime detection)."""

    regime: str  # trending_bull, trending_bear, mean_reverting, high_volatility, low_volatility
    regime_probability: float = Field(ge=0.0, le=1.0)
    hmm_state: int
    transition_probability: float = Field(ge=0.0, le=1.0)
    vol_forecast: float  # GARCH annualized vol forecast
    vol_term_structure: dict[str, float] = Field(default_factory=dict)
    anomaly_score: float = 0.0
    anomaly_detected: bool = False
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SmartMoneyRaw(BaseModel):
    """Raw data from Agent 7: Smart Money flow."""

    symbol: str
    unusual_options_activity: list[dict[str, Any]] = Field(default_factory=list)
    dark_pool_volume: float = 0.0
    dark_pool_pct: float = 0.0
    institutional_holdings_change: float = 0.0
    whale_transactions: list[dict[str, Any]] = Field(default_factory=list)
    social_mentions: int = 0
    social_sentiment: float = Field(ge=-1.0, le=1.0, default=0.0)
    sweep_alerts: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TechnicalSignal(BaseModel):
    """Output from Agent 4: Momentum Bot (technical analysis)."""

    symbol: str
    rsi_14: float
    macd_value: float
    macd_signal: float
    macd_histogram: float
    vwap: float
    price_vs_vwap: float  # % above/below VWAP
    bb_upper: float
    bb_lower: float
    bb_position: float  # 0-1, where price sits in bands
    atr_14: float
    adx: float
    volume_ratio: float  # current vs average
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
