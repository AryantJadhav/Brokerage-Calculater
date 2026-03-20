"""
stock_loader.py
─────────────────────────────────────────────────────────────────────────────
Fetches the complete NSE equity list from NSE's official public data endpoint
and caches it locally so subsequent app launches are instant.

Strategy (in priority order):
  1. Valid local cache (< CACHE_MAX_DAYS old)  → instant, no network
  2. Live fetch from NSE archives CSV           → ~2000 stocks, requires internet
  3. Stale cache (any age)                      → still usable if NSE is down
  4. Bundled static fallback (stock_list.py)    → ~418 stocks, always available

This module is intentionally free of third-party dependencies — only stdlib.
"""

import csv
import io
import json
import urllib.request
from datetime import date
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

CACHE_FILE     = Path(__file__).parent / "nse_stocks_cache.json"
CACHE_MAX_DAYS = 7          # refresh once a week
FETCH_TIMEOUT  = 12         # seconds before giving up on network

# NSE public equity list – all listed equities in CSV format
_NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

# Headers required by NSE's server to serve the file without redirect loop
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Referer":        "https://www.nseindia.com/",
    "Accept":         "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection":     "keep-alive",
}


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_from_nse() -> list[tuple[str, str]]:
    """Download EQUITY_L.csv from NSE archives and return parsed stock list."""
    req = urllib.request.Request(_NSE_URL, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
        raw = resp.read()

    # NSE serves the file as ISO-8859-1 / Windows-1252 on occasion
    for enc in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    stocks: list[tuple[str, str]] = []
    reader = csv.DictReader(io.StringIO(content))

    for row in reader:
        sym  = (row.get("SYMBOL") or "").strip().upper()
        name = (row.get("NAME OF COMPANY") or "").strip()
        # Only EQ series equities; skip Warrants, SME, etc.
        series = (row.get("SERIES") or "").strip()
        if sym and name and series in ("EQ", "BE", "BZ", "IL", ""):
            stocks.append((sym, name))

    return stocks


def _cache_is_fresh() -> bool:
    if not CACHE_FILE.exists():
        return False
    age = (date.today() - date.fromtimestamp(CACHE_FILE.stat().st_mtime)).days
    return age < CACHE_MAX_DAYS


def _read_cache() -> list[tuple[str, str]]:
    with open(CACHE_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    return [tuple(row) for row in data]


def _write_cache(stocks: list[tuple[str, str]]) -> None:
    with open(CACHE_FILE, "w", encoding="utf-8") as fh:
        json.dump(stocks, fh, ensure_ascii=False, separators=(",", ":"))


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def load_stocks() -> tuple[list[tuple[str, str]], str]:
    """
    Return (stocks_list, source_description).

    stocks_list   – list of (SYMBOL, "Company Name") tuples
    source_description – human-readable note for the UI status bar
    """

    # 1 ── Fresh local cache ──────────────────────────────────────────────────
    if _cache_is_fresh():
        try:
            stocks = _read_cache()
            if stocks:
                return stocks, f"NSE live data  ({len(stocks):,} stocks,  cached)"
        except Exception:
            pass

    # 2 ── Live fetch from NSE ────────────────────────────────────────────────
    try:
        stocks = _fetch_from_nse()
        if stocks:
            try:
                _write_cache(stocks)
            except OSError:
                pass  # Cache write failure is non-fatal
            return stocks, f"NSE live data  ({len(stocks):,} stocks,  just fetched)"
    except Exception:
        pass

    # 3 ── Stale cache (better than nothing) ──────────────────────────────────
    if CACHE_FILE.exists():
        try:
            stocks = _read_cache()
            if stocks:
                return stocks, f"NSE cached data  ({len(stocks):,} stocks,  offline fallback)"
        except Exception:
            pass

    # 4 ── Bundled static list ─────────────────────────────────────────────────
    try:
        from stock_list import NSE_STOCKS
        return NSE_STOCKS, f"Static list  ({len(NSE_STOCKS):,} stocks,  offline)"
    except ImportError:
        return [], "No stock data available"
