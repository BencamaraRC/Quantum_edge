"""Quantum Edge Investment Strategy — central configuration.

All strategy constants from the Investment Strategy document v1.0.
Single source of truth for universe, scoring formula, risk parameters,
seasonal priors, and satellite trading rules.
"""

from __future__ import annotations

# ─── Investment Universe ───

MAG7_TIERS: dict[str, list[str]] = {
    "tier1_core": ["NVDA", "GOOGL", "META"],
    "tier2_active": ["AMZN", "MSFT"],
    "tier3_watch": ["AAPL", "TSLA"],
}

# All Mag 7 symbols (flat list)
MAG7_SYMBOLS: list[str] = [s for tier in MAG7_TIERS.values() for s in tier]

# ─── Expanded Universe (10 new primary symbols) ───
EXPANDED_TIERS: dict[str, list[str]] = {
    "tier1_core": ["AMD", "AVGO", "XOM", "LNG", "LLY"],
    "tier2_active": ["NFLX", "CRM", "COIN"],
    "tier3_watch": ["COST", "UBER"],
}

EXPANDED_SYMBOLS: list[str] = [s for tier in EXPANDED_TIERS.values() for s in tier]

# All primary symbols that trade independently (Mag 7 + Expanded)
PRIMARY_SYMBOLS: list[str] = sorted(set(MAG7_SYMBOLS + EXPANDED_SYMBOLS))

SATELLITE_CLUSTERS: dict[str, list[str]] = {
    # Mag 7 anchors (AMD, AVGO, CRM promoted out)
    "NVDA": ["SMCI", "PWR", "FIX", "TSM"],
    "GOOGL": ["TTD", "PUBM", "MGNI", "SNOW", "DDOG"],
    "META": ["SNAP", "PINS", "RDDT"],
    "AMZN": ["NOW", "SHOP", "PANW"],
    "MSFT": ["ADBE", "ORCL", "WDAY", "CRWD"],
    # Expanded anchors
    "AMD": ["MRVL", "INTC", "KLAC"],
    "AVGO": ["MCHP", "SWKS", "QCOM"],
    "XOM": ["CVX", "COP", "OXY"],
    "LNG": ["EQT", "AR"],
    "LLY": ["NVO", "ABBV"],
    "COIN": ["MARA", "MSTR"],
}

# All satellite symbols (flat, deduplicated)
ALL_SATELLITE_SYMBOLS: list[str] = sorted(
    {s for cluster in SATELLITE_CLUSTERS.values() for s in cluster}
)

# Full universe for data collection
FULL_UNIVERSE: list[str] = sorted(set(PRIMARY_SYMBOLS + ALL_SATELLITE_SYMBOLS))


def get_tier(symbol: str) -> str | None:
    """Return tier name for a primary symbol, or None if not primary."""
    for tier_name, symbols in MAG7_TIERS.items():
        if symbol in symbols:
            return tier_name
    for tier_name, symbols in EXPANDED_TIERS.items():
        if symbol in symbols:
            return tier_name
    return None


def get_anchor(satellite: str) -> str | None:
    """Return the Mag 7 anchor for a satellite symbol, or None."""
    for anchor, sats in SATELLITE_CLUSTERS.items():
        if satellite in sats:
            return anchor
    return None


def is_mag7(symbol: str) -> bool:
    return symbol in MAG7_SYMBOLS


def is_primary(symbol: str) -> bool:
    """Return True if symbol trades independently (Mag 7 or Expanded)."""
    return symbol in PRIMARY_SYMBOLS


def is_satellite(symbol: str) -> bool:
    return symbol in ALL_SATELLITE_SYMBOLS


# ─── Composite Formula Weights ───

COMPONENT_WEIGHTS = {
    "agent_signals": 0.60,
    "ds_historical_edge": 0.25,
    "smart_money": 0.15,
}

# Agent signal sub-weights (within the 60% agent_signals component)
AGENT_SIGNAL_WEIGHTS: dict[str, float] = {
    "agent_01": 0.25,  # News sentiment
    "agent_02": 0.30,  # Market data / price action
    "agent_03": 0.20,  # Events calendar
    "agent_04": 0.25,  # Momentum / technicals
}

# Agents that contribute to the "agent_signals" component
AGENT_SIGNAL_IDS = set(AGENT_SIGNAL_WEIGHTS.keys())
DS_EDGE_AGENT_ID = "agent_06"
SMART_MONEY_AGENT_ID = "agent_07"


# ─── Score Bands → Kelly Multiplier ───

SCORE_BANDS: list[tuple[float, float, float]] = [
    (0.93, 1.00, 2.0),  # Maximum conviction — Kelly x2.0 (cap 25% NAV)
    (0.85, 0.92, 1.5),  # High conviction — Kelly x1.5
    (0.75, 0.84, 1.0),  # Standard conviction — Kelly x1.0
]


def kelly_multiplier_for_score(composite_score: float) -> float:
    """Return the Kelly multiplier based on score band."""
    for low, high, mult in SCORE_BANDS:
        if low <= composite_score <= high:
            return mult
    return 1.0


# ─── Seasonal Prior Boosts ───

SEASONAL_PRIORS: dict[str, dict] = {
    "AAPL": {"months": [10, 11], "boost": 0.05, "direction": "long"},
    "GOOGL": {"months": [4], "boost": 0.05, "direction": "long"},
}


def seasonal_boost(symbol: str, month: int, direction: str) -> float:
    """Return seasonal prior boost if applicable, else 0."""
    prior = SEASONAL_PRIORS.get(symbol)
    if prior is None:
        return 0.0
    if month in prior["months"] and direction == prior["direction"]:
        return prior["boost"]
    return 0.0


# ─── Satellite Trading Config ───

SATELLITE_PRIOR_BOOST = 0.05
SATELLITE_KELLY_FRACTION = 0.5
SATELLITE_LAG_WINDOW_HOURS = (2, 6)
MAX_SATELLITES_PER_ANCHOR = 1

# ─── Risk Constants ───

MAX_OPEN_POSITIONS = 5
MIN_RR_RATIO = 2.5
VIX_CIRCUIT_BREAKER = 30.0
VIX_KELLY_RANGE = (18.0, 25.0)
MAX_KELLY_PCT = 25.0  # Max position as % of NAV at max conviction

# ─── Hypotheses (for trade journal tagging) ───

HYPOTHESES = {
    "H1": "Regime-conditional earnings alpha",
    "H2": "Fundamental quality beats EPS magnitude",
    "H3": "Satellite lag creates a second independent entry window",
    "H4": "Seasonal windows raise prior probability of threshold breach",
    "H5": "Multi-source consensus confirmation is non-linear",
    "H6": "Options IV crush signals expected move asymmetry",
    "H7": "VIX modulates Kelly fraction",
    "H8": "Raised guidance outweighs headline EPS surprise",
    "H9": "The false positive is more expensive than the missed trade",
}


def tag_hypotheses(
    symbol: str,
    regime: str,
    is_sat: bool,
    seasonal_applied: bool,
    num_positive_sources: int,
    composite_score: float,
) -> list[str]:
    """Determine which hypotheses are being tested for a given trade."""
    tags = []
    if regime in ("trending_bull", "trending_bear"):
        tags.append("H1")
    if is_sat:
        tags.append("H3")
    if seasonal_applied:
        tags.append("H4")
    if num_positive_sources >= 3:
        tags.append("H5")
    # H9 is always implicitly tested (threshold discipline)
    tags.append("H9")
    return tags
