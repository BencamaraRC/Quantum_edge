"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ─── Redis ───
    redis_url: str = "redis://localhost:6379/0"

    # ─── Database ───
    database_url: str = "postgresql+asyncpg://qe_user:qe_dev_password@localhost:5432/quantum_edge"

    # ─── Alpaca ───
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_url: str = "https://data.alpaca.markets"

    # ─── Data APIs ───
    finnhub_api_key: str = ""
    newsapi_key: str = ""
    unusual_whales_api_key: str = ""

    # ─── Pipeline Thresholds ───
    signal_collection_timeout_s: int = 120
    smart_money_timeout_s: int = 60
    pass1_threshold: float = 0.65
    pass2_threshold: float = 0.75
    max_daily_loss_pct: float = 6.0
    max_position_pct: float = 25.0  # Max position as % of NAV (strategy: 25% at max conviction)
    max_correlated_exposure_pct: float = 15.0

    # ─── Strategy Rules ───
    max_open_positions: int = 3
    min_rr_ratio: float = 2.5
    vix_circuit_breaker_threshold: float = 30.0
    vix_kelly_reduction_start: float = 18.0
    vix_kelly_reduction_end: float = 25.0
    max_kelly_pct: float = 25.0
    satellite_kelly_multiplier: float = 0.5
    satellite_prior_boost: float = 0.05
    seasonal_prior_boost: float = 0.05

    # ─── Options ───
    max_contracts_per_position: int = 10
    max_portfolio_delta: float = 500.0
    max_daily_theta_decay: float = 200.0
    min_option_dte: int = 1  # Minimum days to expiration (0 = allow 0DTE)
    max_option_spread_pct: float = 10.0  # Max bid-ask spread as % of mid price
    allow_naked_shorts: bool = False  # Only defined-risk spreads

    # ─── Trailing Stop / Position Monitor ───
    trailing_stop_activation_pct: float = 3.5
    trailing_stop_trail_pct: float = 1.5
    position_monitor_poll_interval_s: float = 15.0
    position_monitor_enabled: bool = True

    # ─── Monitoring ───
    prometheus_port: int = 9090

    # ─── Logging ───
    log_level: str = "INFO"
    log_format: str = "json"

    # ─── Auth ───
    qe_admin_username: str = "admin"
    qe_admin_password_hash: str = ""
    qe_jwt_secret: str = ""
    qe_jwt_expire_hours: int = 24
    qe_cors_origins: str = "http://localhost:5174,http://localhost:5173"

    # ─── Environment ───
    environment: str = "development"


settings = Settings()
