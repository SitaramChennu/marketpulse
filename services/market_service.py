"""
Live Market Data Service
Fetches real-time index and stock data using Yahoo Finance (free)
"""
import json
import os
import time
import urllib.parse
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

# Major Indian indices and their Yahoo Finance tickers
INDICES = {
    "NIFTY 50": "^NSEI",
    "SENSEX": "^BSESN",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY IT": "^CNXIT",
    "NIFTY NEXT 50": "^NSMIDCP50",
    "NIFTY MIDCAP 150": "NIFTY_MID_SELECT.NS",
    "NIFTY SMALLCAP 250": "^CNXSC",
    "NIFTY 100": "^CNX100",
    "NIFTY 500": "^CRSLDX",
    "NIFTY PHARMA": "^CNXPHARMA",
    "NIFTY FMCG": "^CNXFMCG",
    "NIFTY AUTO": "^CNXAUTO",
    "NIFTY METAL": "^CNXMETAL",
    "NIFTY ENERGY": "^CNXENERGY",
    "NIFTY REALTY": "^CNXREALTY",
    "NIFTY INFRA": "^CNXINFRA",
    "NIFTY PSE": "^CNXPSE",
    "NIFTY PVT BANK": "^NIFTYPVTBANK",
    "NIFTY FIN SERVICE": "NIFTY_FIN_SERVICE.NS",
}

# In-memory cache for live prices (refreshed frequently)
_live_cache: Dict[str, dict] = {}
_last_fetch_time: float = 0
LIVE_CACHE_TTL = 60  # seconds


def get_market_status() -> dict:
    """
    Check if Indian market is currently open.
    Market hours: Mon-Fri, 9:15 AM - 3:30 PM IST
    """
    now = datetime.now()
    
    # Check if weekend
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return {
            "is_open": False,
            "status": "closed",
            "message": "Market closed (Weekend)",
            "next_open": "Monday 9:15 AM"
        }
    
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    if now < market_open:
        return {
            "is_open": False,
            "status": "pre_market",
            "message": "Market opens at 9:15 AM",
            "next_open": "Today 9:15 AM"
        }
    elif now > market_close:
        return {
            "is_open": False,
            "status": "post_market",
            "message": "Market closed for today (3:30 PM)",
            "next_open": "Tomorrow 9:15 AM" if now.weekday() < 4 else "Monday 9:15 AM"
        }
    else:
        return {
            "is_open": True,
            "status": "open",
            "message": "Market is LIVE",
            "closes_at": "3:30 PM"
        }


def fetch_live_index_data(ticker: str) -> Optional[dict]:
    """Fetch current price data for an index using direct Yahoo Finance chart API."""
    try:
        encoded = urllib.parse.quote(ticker)
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?interval=1d&range=2d"
        r = requests.get(url, headers=HTTP_HEADERS, timeout=5)
        if r.status_code == 200:
            data = r.json()
            result = data.get("chart", {}).get("result", [])
            if result:
                meta = result[0].get("meta", {})
                current_price = meta.get("regularMarketPrice")
                previous_close = meta.get("chartPreviousClose") or meta.get("previousClose")
                
                # Fallback to indicators close array
                if previous_close is None:
                    closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    if len(closes) >= 2:
                        previous_close = closes[0]
                    elif len(closes) == 1:
                        previous_close = closes[0]
                        
                if current_price and previous_close:
                    change = current_price - previous_close
                    change_pct = (change / previous_close) * 100
                    return {
                        "ticker": ticker,
                        "current_price": round(float(current_price), 2),
                        "previous_close": round(float(previous_close), 2),
                        "change": round(float(change), 2),
                        "change_pct": round(float(change_pct), 2),
                        "timestamp": datetime.now().isoformat()
                    }
    except Exception as e:
        print(f"Error fetching {ticker}: {e}")
    return None


def fetch_all_indices() -> Dict[str, dict]:
    """Fetch live data for all major indices with fast direct HTTP requests."""
    global _live_cache, _last_fetch_time
    
    # Return cache if fresh (< 60s)
    if time.time() - _last_fetch_time < LIVE_CACHE_TTL and _live_cache:
        return _live_cache
    
    results = {}
    for name, ticker in INDICES.items():
        try:
            data = fetch_live_index_data(ticker)
            if data:
                data["name"] = name
                results[ticker] = data
        except Exception as e:
            continue
            
    if results:
        _live_cache = results
        _last_fetch_time = time.time()
        
    return _live_cache if _live_cache else results


def get_index_change(ticker: str) -> Optional[float]:
    """
    Get the percentage change for a specific index.
    Returns the change percentage or None if unavailable.
    """
    indices = fetch_all_indices()
    
    if ticker in indices:
        return indices[ticker]["change_pct"]
    
    # Try individual fetch if not in cache
    result = fetch_live_index_data(ticker)
    if result:
        return result["change_pct"]
    
    return None


def get_nifty50_change() -> Optional[float]:
    """Get Nifty 50 percentage change - most commonly needed."""
    return get_index_change("^NSEI")
