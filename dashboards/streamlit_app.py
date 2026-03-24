"""Quantum Edge Trading Dashboard — Streamlit."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Quantum Edge",
    page_icon="⚡",
    layout="wide",
)

st.title("Quantum Edge Trading Dashboard")

# ─── Sidebar: Kill Switch & Controls ───
with st.sidebar:
    st.header("Controls")

    if st.button("KILL SWITCH", type="primary", use_container_width=True):
        st.warning("Kill switch activated — cancelling all orders and closing positions")
        # TODO: publish kill switch event to Redis

    st.divider()
    st.subheader("Agent Status")
    agents = [
        ("Agent 1", "News Scanner"),
        ("Agent 2", "Market Data"),
        ("Agent 3", "Events Engine"),
        ("Agent 4", "Momentum Bot"),
        ("Agent 5", "Risk Guard"),
        ("Agent 6", "Data Scientist"),
        ("Agent 7", "Smart Money"),
    ]
    for agent_id, name in agents:
        st.text(f"🟢 {agent_id}: {name}")

    st.divider()
    st.subheader("Pipeline")
    st.text("Coordinator: 🟢 Running")
    st.text("Active Memos: 0")

# ─── Main Content ───

tab1, tab2, tab3, tab4 = st.tabs(["Portfolio", "Active Memos", "Trade History", "Regime"])

with tab1:
    st.subheader("Portfolio Overview")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Equity", "$100,000", "+$250")
    with col2:
        st.metric("Daily P&L", "+$250", "+0.25%")
    with col3:
        st.metric("Open Positions", "3")
    with col4:
        st.metric("Buying Power", "$75,000")

    st.divider()

    # Placeholder positions table
    st.subheader("Open Positions")
    positions_df = pd.DataFrame({
        "Symbol": ["AAPL", "NVDA", "TSLA"],
        "Side": ["LONG", "LONG", "SHORT"],
        "Qty": [50, 30, 20],
        "Entry": [175.50, 480.25, 250.00],
        "Current": [178.00, 485.50, 248.50],
        "P&L": [125.00, 157.50, 30.00],
        "P&L %": [1.43, 1.09, 0.60],
    })
    st.dataframe(positions_df, use_container_width=True)

with tab2:
    st.subheader("Active Investment Memos")
    st.info("No active memos — waiting for signals...")

with tab3:
    st.subheader("Trade History")

    # Placeholder trade log
    trades_df = pd.DataFrame({
        "Time": pd.date_range(end=datetime.now(), periods=5, freq="h"),
        "Symbol": ["AAPL", "NVDA", "TSLA", "AMD", "GOOGL"],
        "Side": ["LONG", "LONG", "SHORT", "LONG", "LONG"],
        "Entry": [175.50, 480.25, 252.00, 120.50, 140.00],
        "Exit": [178.00, 485.50, 248.50, 118.00, 143.50],
        "P&L": [125.00, 157.50, 70.00, -125.00, 175.00],
        "Result": ["Win", "Win", "Win", "Loss", "Win"],
    })
    st.dataframe(trades_df, use_container_width=True)

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Win Rate", "80%")
    with col2:
        st.metric("Total P&L", "+$402.50")
    with col3:
        st.metric("Avg R:R", "2.1:1")

with tab4:
    st.subheader("Market Regime (Agent 6)")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Current Regime", "Trending Bull")
    with col2:
        st.metric("Regime Probability", "85%")
    with col3:
        st.metric("Vol Forecast", "18.5%")

    st.divider()
    st.subheader("Regime History")
    st.line_chart(
        pd.DataFrame(
            {
                "Trending Bull": [0.3, 0.5, 0.7, 0.85, 0.82, 0.78, 0.85],
                "Mean Reverting": [0.4, 0.3, 0.2, 0.10, 0.12, 0.15, 0.10],
                "High Volatility": [0.3, 0.2, 0.1, 0.05, 0.06, 0.07, 0.05],
            },
            index=pd.date_range(end=datetime.now(), periods=7, freq="D"),
        )
    )
