"""
NAV Estimation Engine
Estimates live NAV changes based on benchmark index movements
"""
import json
import os
import re
from typing import Optional, Dict, List
from datetime import datetime

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")


def load_benchmark_config() -> dict:
    """Load benchmark configuration."""
    config_path = os.path.join(CONFIG_DIR, "benchmarks.json")
    with open(config_path, "r") as f:
        return json.load(f)


def classify_fund(scheme_name: str, category: str = "") -> dict:
    """
    Classify a mutual fund based on its name and category.
    Returns fund type, sub-type, and estimated benchmark ticker.
    """
    name_lower = scheme_name.lower()
    cat_lower = category.lower()
    
    result = {
        "fund_type": "equity",
        "sub_type": "unknown",
        "benchmark_ticker": "^NSEI",  # Default to Nifty 50
        "benchmark_name": "NIFTY 50",
        "equity_pct": 100,  # Estimated equity percentage
    }
    
    # === DEBT FUNDS ===
    debt_keywords = ["liquid", "money market", "overnight", "ultra short",
                     "low duration", "short duration", "medium duration",
                     "long duration", "gilt", "credit risk", "banking & psu",
                     "corporate bond", "dynamic bond", "floater", "debt"]
    if any(kw in name_lower for kw in debt_keywords) or "debt" in cat_lower:
        result["fund_type"] = "debt"
        result["benchmark_ticker"] = None
        result["benchmark_name"] = "Debt (No live estimate)"
        result["equity_pct"] = 0
        return result
    
    # === HYBRID FUNDS ===
    if "hybrid" in name_lower or "hybrid" in cat_lower:
        result["fund_type"] = "hybrid"
        if "aggressive" in name_lower or "aggressive" in cat_lower:
            result["sub_type"] = "aggressive_hybrid"
            result["equity_pct"] = 75
        elif "conservative" in name_lower or "conservative" in cat_lower:
            result["sub_type"] = "conservative_hybrid"
            result["equity_pct"] = 25
        elif "balanced advantage" in name_lower or "dynamic" in name_lower:
            result["sub_type"] = "balanced_advantage"
            result["equity_pct"] = 55
        elif "equity savings" in name_lower:
            result["sub_type"] = "equity_savings"
            result["equity_pct"] = 35
        else:
            result["sub_type"] = "hybrid"
            result["equity_pct"] = 60
        result["benchmark_name"] = "NIFTY 50 (Equity portion)"
        return result
    
    # === INDEX FUNDS & ETFs ===
    if "index" in name_lower or "etf" in name_lower:
        result["sub_type"] = "index"
        
        index_map = {
            "nifty 50": ("^NSEI", "NIFTY 50"),
            "nifty50": ("^NSEI", "NIFTY 50"),
            "sensex": ("^BSESN", "SENSEX"),
            "nifty next 50": ("^NSMIDCP50", "NIFTY NEXT 50"),
            "nifty 100": ("^CNX100", "NIFTY 100"),
            "nifty bank": ("^NSEBANK", "NIFTY BANK"),
            "bank nifty": ("^NSEBANK", "NIFTY BANK"),
            "nifty it": ("^CNXIT", "NIFTY IT"),
            "nifty midcap": ("NIFTY_MID_SELECT.NS", "NIFTY MIDCAP"),
            "midcap 150": ("NIFTY_MID_SELECT.NS", "NIFTY MIDCAP 150"),
            "nifty smallcap": ("^CNXSC", "NIFTY SMALLCAP"),
            "smallcap 250": ("^CNXSC", "NIFTY SMALLCAP 250"),
            "nifty 500": ("^CRSLDX", "NIFTY 500"),
            "nifty pharma": ("^CNXPHARMA", "NIFTY PHARMA"),
            "nifty auto": ("^CNXAUTO", "NIFTY AUTO"),
            "nifty fmcg": ("^CNXFMCG", "NIFTY FMCG"),
            "nifty metal": ("^CNXMETAL", "NIFTY METAL"),
            "nifty energy": ("^CNXENERGY", "NIFTY ENERGY"),
            "nifty realty": ("^CNXREALTY", "NIFTY REALTY"),
            "nifty infra": ("^CNXINFRA", "NIFTY INFRA"),
            "nifty pse": ("^CNXPSE", "NIFTY PSE"),
            "nifty private bank": ("^NIFTYPVTBANK", "NIFTY PVT BANK"),
            "nifty financial": ("NIFTY_FIN_SERVICE.NS", "NIFTY FIN SERVICE"),
        }
        
        for keyword, (ticker, name) in index_map.items():
            if keyword in name_lower:
                result["benchmark_ticker"] = ticker
                result["benchmark_name"] = name
                break
        
        return result
    
    # === SECTOR FUNDS ===
    sector_map = {
        "banking": ("^NSEBANK", "NIFTY BANK"),
        "financial": ("NIFTY_FIN_SERVICE.NS", "NIFTY FIN SERVICE"),
        "technology": ("^CNXIT", "NIFTY IT"),
        "pharma": ("^CNXPHARMA", "NIFTY PHARMA"),
        "healthcare": ("^CNXPHARMA", "NIFTY PHARMA"),
        "fmcg": ("^CNXFMCG", "NIFTY FMCG"),
        "consumption": ("^CNXFMCG", "NIFTY FMCG"),
        "auto": ("^CNXAUTO", "NIFTY AUTO"),
        "metal": ("^CNXMETAL", "NIFTY METAL"),
        "energy": ("^CNXENERGY", "NIFTY ENERGY"),
        "infrastructure": ("^CNXINFRA", "NIFTY INFRA"),
        "realty": ("^CNXREALTY", "NIFTY REALTY"),
        "real estate": ("^CNXREALTY", "NIFTY REALTY"),
        "psu": ("^CNXPSE", "NIFTY PSE"),
    }
    
    for keyword, (ticker, name) in sector_map.items():
        if keyword in name_lower:
            result["sub_type"] = f"sector_{keyword}"
            result["benchmark_ticker"] = ticker
            result["benchmark_name"] = name
            return result
    
    # === EQUITY CATEGORIES ===
    if "small" in name_lower and "cap" in name_lower:
        result["sub_type"] = "small_cap"
        result["benchmark_ticker"] = "^CNXSC"
        result["benchmark_name"] = "NIFTY SMALLCAP"
    elif "mid" in name_lower and "cap" in name_lower:
        result["sub_type"] = "mid_cap"
        result["benchmark_ticker"] = "NIFTY_MID_SELECT.NS"
        result["benchmark_name"] = "NIFTY MIDCAP"
    elif "large" in name_lower and "mid" in name_lower:
        result["sub_type"] = "large_mid_cap"
        result["benchmark_ticker"] = "^CNX100"
        result["benchmark_name"] = "NIFTY 100"
    elif "large" in name_lower and "cap" in name_lower:
        result["sub_type"] = "large_cap"
        result["benchmark_ticker"] = "^NSEI"
        result["benchmark_name"] = "NIFTY 50"
    elif "flexi" in name_lower or "multi" in name_lower:
        result["sub_type"] = "flexi_cap"
        result["benchmark_ticker"] = "^NSEI"
        result["benchmark_name"] = "NIFTY 50"
    elif "elss" in name_lower or "tax" in name_lower:
        result["sub_type"] = "elss"
        result["benchmark_ticker"] = "^NSEI"
        result["benchmark_name"] = "NIFTY 50"
    elif "value" in name_lower or "contra" in name_lower:
        result["sub_type"] = "value"
        result["benchmark_ticker"] = "^NSEI"
        result["benchmark_name"] = "NIFTY 50"
    elif "focused" in name_lower:
        result["sub_type"] = "focused"
        result["benchmark_ticker"] = "^NSEI"
        result["benchmark_name"] = "NIFTY 50"
    elif "dividend" in name_lower and "yield" in name_lower:
        result["sub_type"] = "dividend_yield"
        result["benchmark_ticker"] = "^NSEI"
        result["benchmark_name"] = "NIFTY 50"
    
    return result


def estimate_nav(
    previous_nav: float,
    benchmark_change_pct: float,
    equity_pct: float = 100,
    expense_ratio: float = 0.005  # ~0.5% annual, daily impact
) -> dict:
    """
    Estimate the new NAV based on benchmark movement.
    
    For index funds: NAV tracks the index very closely
    For active funds: Benchmark is used as a proxy (less accurate)
    For hybrid: Only equity portion moves with the index
    """
    # Daily expense ratio impact (annual / 365)
    daily_expense = expense_ratio / 365
    
    # Equity portion moves with the benchmark
    equity_change = (equity_pct / 100) * (benchmark_change_pct / 100)
    
    # Debt portion stays roughly flat (small daily accrual)
    debt_pct = 100 - equity_pct
    debt_daily_return = 0.02 / 100  # ~7% annual / 365 ≈ 0.02% daily
    debt_change = (debt_pct / 100) * debt_daily_return
    
    # Total estimated change
    total_change_pct = (equity_change + debt_change - daily_expense) * 100
    
    # Estimated new NAV
    estimated_nav = previous_nav * (1 + total_change_pct / 100)
    nav_change = estimated_nav - previous_nav
    
    return {
        "previous_nav": round(previous_nav, 4),
        "estimated_nav": round(estimated_nav, 4),
        "nav_change": round(nav_change, 4),
        "nav_change_pct": round(total_change_pct, 4),
        "benchmark_change_pct": round(benchmark_change_pct, 2),
        "equity_pct": equity_pct,
        "is_estimate": True,
        "confidence": "High" if equity_pct == 100 else "Medium" if equity_pct >= 60 else "Low"
    }


def estimate_nav_for_fund(fund_data: dict, index_changes: Dict[str, float]) -> Optional[dict]:
    """
    Estimate NAV change for a specific fund using live index data.
    
    Args:
        fund_data: Fund info from AMFI (scheme_name, nav, etc.)
        index_changes: Dict of {ticker: change_pct}
    
    Returns:
        Estimated NAV data or None if estimation not possible
    """
    if not fund_data or not fund_data.get("nav"):
        return None
    
    # Classify the fund
    classification = classify_fund(
        fund_data.get("scheme_name", ""),
        fund_data.get("category", "")
    )
    
    benchmark_ticker = classification["benchmark_ticker"]
    
    # Debt funds can't be estimated from equity indices
    if benchmark_ticker is None:
        return {
            "scheme_code": fund_data.get("scheme_code"),
            "scheme_name": fund_data.get("scheme_name"),
            "previous_nav": fund_data.get("nav"),
            "estimated_nav": fund_data.get("nav"),
            "nav_change": 0,
            "nav_change_pct": 0,
            "benchmark_name": classification["benchmark_name"],
            "fund_type": classification["fund_type"],
            "sub_type": classification["sub_type"],
            "is_estimate": False,
            "confidence": "N/A",
            "message": "Debt fund - NAV changes are minimal daily"
        }
    
    # Get benchmark change
    benchmark_change = index_changes.get(benchmark_ticker)
    
    if benchmark_change is None:
        # Try Nifty 50 as fallback
        benchmark_change = index_changes.get("^NSEI")
        if benchmark_change is None:
            return None
    
    # Estimate the NAV
    estimation = estimate_nav(
        previous_nav=fund_data["nav"],
        benchmark_change_pct=benchmark_change,
        equity_pct=classification["equity_pct"]
    )
    
    # Add fund metadata
    estimation.update({
        "scheme_code": fund_data.get("scheme_code"),
        "scheme_name": fund_data.get("scheme_name"),
        "amc": fund_data.get("amc", ""),
        "category": fund_data.get("category", ""),
        "nav_date": fund_data.get("nav_date", ""),
        "benchmark_name": classification["benchmark_name"],
        "benchmark_ticker": benchmark_ticker,
        "fund_type": classification["fund_type"],
        "sub_type": classification["sub_type"],
    })
    
    return estimation
