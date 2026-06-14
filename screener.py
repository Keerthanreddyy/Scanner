"""
screener.py — Core stock screening logic.

Fetches data via yfinance, computes RSI, volume ratio, P/E,
filters by criteria, and yields results as they are ready.
"""

import time
import math
import logging
import numpy as np
import yfinance as yf
import pandas as pd
from typing import Generator

log = logging.getLogger(__name__)

# ── Screening thresholds ───────────────────────────────────────────────────────
PE_MAX          = 20.0
VOLUME_SPIKE    = 2.0   # current vol > 2× 20-day avg
RSI_MIN         = 50.0

# ── yfinance fetch parameters ─────────────────────────────────────────────────
HISTORY_PERIOD  = "30d"   # enough for 20-day vol avg + 14-day RSI
BATCH_SIZE      = 5       # tickers per yf.download() call
BATCH_DELAY     = 1.5     # seconds between batches (rate-limit courtesy)


def _rsi(series: pd.Series, period: int = 14) -> float:
    """Compute the most-recent RSI value for a price series."""
    delta = series.diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    # Wilder's smoothing (EMA with α = 1/period)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else float("nan")


def _score(pe: float, vol_ratio: float, rsi: float) -> float:
    """Composite rank score — higher is better."""
    return (1 / pe) * 0.4 + vol_ratio * 0.3 + (rsi - 50) * 0.3


def _safe_float(val) -> float | None:
    try:
        v = float(val)
        return None if (math.isnan(v) or math.isinf(v)) else v
    except Exception:
        return None


def _fetch_batch(tickers: list[str]) -> dict:
    """
    Download 30 days of OHLCV for a batch of tickers.
    Returns a dict keyed by ticker with a DataFrame.
    """
    if not tickers:
        return {}
    joined = " ".join(tickers)
    try:
        raw = yf.download(
            joined,
            period=HISTORY_PERIOD,
            interval="1d",
            group_by="ticker",
            auto_adjust=True,
            progress=False,
            threads=True,
        )
    except Exception as e:
        log.warning("Batch download failed: %s", e)
        return {}

    result = {}
    # Single ticker → flat DataFrame; multiple → MultiIndex
    if len(tickers) == 1:
        t = tickers[0]
        if not raw.empty:
            result[t] = raw
    else:
        for t in tickers:
            try:
                df = raw[t].dropna(how="all")
                if not df.empty:
                    result[t] = df
            except KeyError:
                pass
    return result


def _get_pe(ticker: str) -> float | None:
    """Fetch P/E ratio from yfinance Info (slower — 1 call per ticker)."""
    try:
        info = yf.Ticker(ticker).fast_info
        # fast_info has 'pe_forward' on some, fall back to None
        pe = getattr(info, "pe_forward", None)
        if pe is None or (isinstance(pe, float) and math.isnan(pe)):
            # Fall back to trailing P/E via .info dict
            full = yf.Ticker(ticker).info
            pe = full.get("trailingPE") or full.get("forwardPE")
        return _safe_float(pe)
    except Exception:
        return None


def screen(
    tickers: list[str],
    progress_cb=None,
) -> Generator[dict, None, None]:
    """
    Yield result dicts for each stock that passes all filters, in the order
    they are found. Caller can sort/rank afterwards.

    progress_cb(done, total) — optional callback for progress updates.
    """
    total   = len(tickers)
    done    = 0
    batches = [tickers[i:i + BATCH_SIZE] for i in range(0, total, BATCH_SIZE)]

    for batch in batches:
        hist_map = _fetch_batch(batch)

        for ticker in batch:
            done += 1
            if progress_cb:
                progress_cb(done, total)

            df = hist_map.get(ticker)
            if df is None or len(df) < 15:
                continue  # not enough data

            # ── Volume ratio ────────────────────────────────────────────────
            vol_series   = df["Volume"]
            current_vol  = float(vol_series.iloc[-1])
            avg_vol_20   = float(vol_series.iloc[-21:-1].mean()) if len(vol_series) >= 21 else float(vol_series.mean())
            if avg_vol_20 == 0:
                continue
            vol_ratio = current_vol / avg_vol_20
            if vol_ratio < VOLUME_SPIKE:
                continue

            # ── RSI ─────────────────────────────────────────────────────────
            close = df["Close"]
            rsi   = _rsi(close)
            if math.isnan(rsi) or rsi < RSI_MIN:
                continue

            # ── P/E ratio (requires separate API call) ───────────────────
            pe = _get_pe(ticker)
            if pe is None or pe <= 0 or pe >= PE_MAX:
                continue

            # ── Current price ────────────────────────────────────────────
            price = _safe_float(close.iloc[-1])

            score = _score(pe, vol_ratio, rsi)

            yield {
                "ticker":     ticker,
                "price":      round(price, 2) if price else None,
                "pe":         round(pe, 2),
                "vol_ratio":  round(vol_ratio, 2),
                "rsi":        round(rsi, 2),
                "score":      round(score, 4),
            }

        # ── Rate-limit courtesy pause between batches ────────────────────
        time.sleep(BATCH_DELAY)
