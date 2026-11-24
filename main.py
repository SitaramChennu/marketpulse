"""
MarketPulse - Main FastAPI Application
Live investments and Indian market intelligence platform
"""
import os
import sys
import json
from datetime import datetime
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from services.amfi_service import fetch_all_nav, search_funds, get_fund_nav, get_fund_nav_history
from services.market_service import fetch_all_indices, get_index_change, get_market_status, INDICES
from services.estimator import estimate_nav_for_fund, classify_fund
from services.database import (
    add_to_portfolio, remove_from_portfolio, get_portfolio,
    add_to_watchlist, remove_from_watchlist, get_watchlist,
    register_user, login_user, get_user_from_token, logout_user
)

# --- Global State ---
_all_funds_cache = {}
_index_data_cache = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-load data on startup."""
    global _all_funds_cache, _index_data_cache
    print("🚀 Starting NAV Estimator...")
    print("📊 Loading fund data from AMFI...")
    _all_funds_cache = fetch_all_nav()
    print(f"✅ Loaded {len(_all_funds_cache)} funds")
    try:
        _index_data_cache = fetch_all_indices()
        print(f"📈 Loaded {len(_index_data_cache)} live indices")
    except Exception as e:
        print(f"⚠️ Index load warning: {e}")
    yield
    print("👋 Shutting down MarketPulse")


app = FastAPI(
    title="MarketPulse",
    description="Live market and investment intelligence platform",
    version="2.0.0",
    lifespan=lifespan
)

# Serve static files
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Pydantic Models ---
class PortfolioAdd(BaseModel):
    scheme_code: str
    scheme_name: str
    units: float
    avg_buy_nav: Optional[float] = None
    invested_amount: Optional[float] = None


class WatchlistAdd(BaseModel):
    scheme_code: str
    scheme_name: str


class UserAuth(BaseModel):
    username: str
    password: str


def resolve_user(authorization: Optional[str] = None) -> Optional[dict]:
    """Helper to extract user from Authorization header token."""
    token = None
    if authorization:
        if authorization.startswith("Bearer "):
            token = authorization.split("Bearer ", 1)[1].strip()
        else:
            token = authorization.strip()
    return get_user_from_token(token)


# --- Authentication Routes ---

@app.post("/api/auth/register")
async def api_register(req: UserAuth):
    """Sign up a new user."""
    user, err = register_user(req.username, req.password)
    if err:
        return {"status": "error", "message": err}
    return {"status": "success", "user": user}


@app.post("/api/auth/login")
async def api_login(req: UserAuth):
    """Log in an existing user."""
    user, err = login_user(req.username, req.password)
    if err:
        return {"status": "error", "message": err}
    return {"status": "success", "user": user}


@app.get("/api/auth/me")
async def api_me(authorization: Optional[str] = Header(None)):
    """Get currently logged-in user profile."""
    user = resolve_user(authorization)
    if not user:
        return {"status": "unauthenticated", "user": None}
    return {"status": "success", "user": user}


@app.post("/api/auth/logout")
async def api_logout(authorization: Optional[str] = Header(None)):
    """Log out user by invalidating token."""
    token = None
    if authorization:
        token = authorization.replace("Bearer ", "").strip()
    logout_user(token)
    return {"status": "success"}


# --- PWA & Frontend Routes ---

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main dashboard."""
    html_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(html_path):
        return FileResponse(html_path)
    return HTMLResponse("<h1>NAV Estimator</h1><p>Frontend not found. Place index.html in /static/</p>")


@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(os.path.join(STATIC_DIR, "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js")
async def get_sw():
    return FileResponse(os.path.join(STATIC_DIR, "sw.js"), media_type="application/javascript")


@app.get("/api/market/status")
async def api_market_status():
    """Get current market status (open/closed)."""
    return get_market_status()


@app.get("/api/market/indices")
async def api_market_indices():
    """Get live data for all major indices."""
    global _index_data_cache
    try:
        _index_data_cache = fetch_all_indices()
        return {
            "status": "success",
            "count": len(_index_data_cache),
            "data": _index_data_cache,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "data": _index_data_cache}


@app.get("/api/funds/search")
async def api_search_funds(q: str = Query(..., min_length=2, description="Search query")):
    """Search mutual funds by name, scheme code, or ISIN with smart matching."""
    global _all_funds_cache, _index_data_cache
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    results = search_funds(q, _all_funds_cache)
    
    # Attach live estimations from memory cache if available (instant response)
    index_changes = {ticker: data["change_pct"] for ticker, data in _index_data_cache.items()} if _index_data_cache else {}
    
    # Add classification & estimation info to each result
    for fund in results:
        classification = classify_fund(fund.get("scheme_name", ""), fund.get("category", ""))
        fund["classification"] = classification
        if index_changes:
            est = estimate_nav_for_fund(fund, index_changes)
            if est:
                fund["estimation"] = est
    
    return {
        "status": "success",
        "count": len(results),
        "query": q,
        "results": results
    }


@app.get("/api/funds/all")
async def api_all_funds(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
    category: Optional[str] = None,
    amc: Optional[str] = None
):
    """Get all funds with pagination and filtering."""
    global _all_funds_cache
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    funds_list = []
    for code, fund in _all_funds_cache.items():
        if code.startswith("_"):
            continue
        
        # Apply filters
        if category and category.lower() not in fund.get("category", "").lower():
            continue
        if amc and amc.lower() not in fund.get("amc", "").lower():
            continue
        
        funds_list.append(fund)
    
    # Sort by scheme name
    funds_list.sort(key=lambda x: x.get("scheme_name", ""))
    
    # Paginate
    total = len(funds_list)
    start = (page - 1) * per_page
    end = start + per_page
    page_data = funds_list[start:end]
    
    return {
        "status": "success",
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "results": page_data
    }


@app.get("/api/funds/{scheme_code}")
async def api_fund_detail(scheme_code: str):
    """Get detailed info for a specific fund."""
    global _all_funds_cache
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    fund = _all_funds_cache.get(scheme_code)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")
    
    classification = classify_fund(fund.get("scheme_name", ""), fund.get("category", ""))
    fund["classification"] = classification
    
    return {"status": "success", "data": fund}


@app.get("/api/funds/{scheme_code}/history")
async def api_fund_history(scheme_code: str):
    """Get NAV history for a fund."""
    history = get_fund_nav_history(scheme_code)
    return {
        "status": "success",
        "scheme_code": scheme_code,
        "count": len(history),
        "data": history[:365]  # Last 1 year
    }


@app.get("/api/funds/{scheme_code}/nav_at_date")
async def api_nav_at_date(scheme_code: str, date: str = Query(..., description="Date in YYYY-MM-DD format")):
    """Get exact or closest historical NAV on or before a given date."""
    history = get_fund_nav_history(scheme_code)
    if not history:
        return {"status": "error", "message": "Historical NAV data not available for this scheme"}
    
    target_date = None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            target_date = datetime.strptime(date.strip(), fmt).date()
            break
        except ValueError:
            continue
            
    if not target_date:
        return {"status": "error", "message": "Invalid date format. Please use YYYY-MM-DD"}
        
    best_match = None
    for entry in history:
        try:
            entry_d = datetime.strptime(entry["date"], "%d-%m-%Y").date()
            if entry_d <= target_date:
                best_match = entry
                break
        except Exception:
            continue
            
    if best_match:
        return {
            "status": "success",
            "scheme_code": scheme_code,
            "target_date": target_date.strftime("%Y-%m-%d"),
            "matched_date": best_match["date"],
            "nav": best_match["nav"]
        }
    else:
        oldest = history[-1] if history else None
        return {
            "status": "success",
            "scheme_code": scheme_code,
            "target_date": target_date.strftime("%Y-%m-%d"),
            "matched_date": oldest["date"] if oldest else None,
            "nav": oldest["nav"] if oldest else None,
            "note": "Date precedes available history; earliest NAV returned"
        }


@app.get("/api/estimate/fund/{scheme_code}")
async def api_estimate_fund(scheme_code: str):
    """Get estimated NAV for a specific fund."""
    global _all_funds_cache, _index_data_cache
    
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    fund = _all_funds_cache.get(scheme_code)
    if not fund:
        raise HTTPException(status_code=404, detail="Fund not found")
    
    # Fetch latest index data
    if not _index_data_cache:
        _index_data_cache = fetch_all_indices()
    
    # Build index changes map
    index_changes = {ticker: data["change_pct"] for ticker, data in _index_data_cache.items()}
    
    estimation = estimate_nav_for_fund(fund, index_changes)
    if not estimation:
        return {"status": "error", "message": "Could not estimate NAV for this fund"}
    
    market_status = get_market_status()
    estimation["market_status"] = market_status
    
    return {"status": "success", "data": estimation}


@app.get("/api/estimate/all")
async def api_estimate_all(
    q: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200)
):
    """Get estimated NAV for all funds (or filtered)."""
    global _all_funds_cache, _index_data_cache
    
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    # Refresh index data
    _index_data_cache = fetch_all_indices()
    index_changes = {ticker: data["change_pct"] for ticker, data in _index_data_cache.items()}
    
    # If search query is provided, use smart search
    if q:
        candidate_funds = search_funds(q, _all_funds_cache)
    else:
        candidate_funds = [f for code, f in _all_funds_cache.items() if not code.startswith("_")]
    
    estimations = []
    for fund in candidate_funds:
        if category and category.lower() not in fund.get("category", "").lower():
            continue
        
        estimation = estimate_nav_for_fund(fund, index_changes)
        if estimation:
            estimations.append(estimation)
    
    # Sort by absolute NAV change percentage (biggest movers first)
    estimations.sort(key=lambda x: abs(x.get("nav_change_pct", 0)), reverse=True)
    
    total = len(estimations)
    start = (page - 1) * per_page
    end = start + per_page
    
    market_status = get_market_status()
    
    return {
        "status": "success",
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": (total + per_page - 1) // per_page,
        "market_status": market_status,
        "results": estimations[start:end],
        "timestamp": datetime.now().isoformat()
    }


# --- Portfolio Routes ---

@app.get("/api/portfolio")
async def api_get_portfolio(authorization: Optional[str] = Header(None)):
    """Get user's portfolio with live estimations."""
    global _all_funds_cache, _index_data_cache
    
    user = resolve_user(authorization)
    if not user:
        return {
            "status": "unauthenticated",
            "message": "Please log in to view your portfolio",
            "user": None,
            "data": [],
            "summary": {
                "total_invested": 0, "total_current": 0,
                "total_estimated_current": 0, "total_return": 0,
                "total_return_pct": 0, "day_change": 0, "day_change_pct": 0
            }
        }
        
    portfolio = get_portfolio(user["id"])
    
    if not portfolio:
        return {"status": "success", "user": user, "data": [], "summary": {"total_invested": 0, "total_current": 0}}
    
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    # Refresh index data
    try:
        _index_data_cache = fetch_all_indices()
    except:
        pass
    
    index_changes = {ticker: data["change_pct"] for ticker, data in _index_data_cache.items()}
    
    enriched = []
    total_invested = 0
    total_current = 0
    total_estimated_current = 0
    total_1d_change = 0
    
    for holding in portfolio:
        scheme_code = holding["scheme_code"]
        units = holding["units"]
        invested = holding.get("invested_amount", 0) or 0
        avg_nav = holding.get("avg_buy_nav", 0) or 0
        
        fund = _all_funds_cache.get(scheme_code, {})
        current_nav = fund.get("nav", 0) or 0
        
        # Get estimation
        estimation = estimate_nav_for_fund(fund, index_changes) if fund else None
        
        estimated_nav = estimation["estimated_nav"] if estimation and estimation.get("estimated_nav") else current_nav
        nav_change_pct = estimation["nav_change_pct"] if estimation and estimation.get("nav_change_pct") else 0
        
        # Get classification even if estimation fails
        if not estimation:
            from services.estimator import classify_fund
            cls = classify_fund(fund.get("scheme_name", ""), fund.get("category", ""))
        else:
            cls = None
        
        current_value = current_nav * units
        estimated_value = estimated_nav * units
        day_change = estimated_value - current_value
        
        # Calculate total returns
        if invested > 0:
            total_return = current_value - invested
            total_return_pct = (total_return / invested) * 100
        elif avg_nav > 0:
            invested = avg_nav * units
            total_return = current_value - invested
            total_return_pct = (total_return / invested) * 100
        else:
            invested = 0
            total_return = 0
            total_return_pct = 0
        
        entry = {
            **holding,
            "current_nav": current_nav,
            "estimated_nav": round(estimated_nav, 4),
            "nav_change_pct": round(nav_change_pct, 4),
            "current_value": round(current_value, 2),
            "estimated_value": round(estimated_value, 2),
            "day_change": round(day_change, 2),
            "invested_amount": round(invested, 2),
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "fund_type": estimation.get("fund_type", cls.get("fund_type", "unknown") if cls else "unknown") if estimation else (cls.get("fund_type", "unknown") if cls else "unknown"),
            "benchmark_name": estimation.get("benchmark_name", cls.get("benchmark_name", "") if cls else "") if estimation else (cls.get("benchmark_name", "") if cls else ""),
            "confidence": estimation.get("confidence", "N/A") if estimation else "N/A",
            "nav_date": fund.get("nav_date", ""),
            "category": fund.get("category", ""),
        }
        
        enriched.append(entry)
        total_invested += invested
        total_current += current_value
        total_estimated_current += estimated_value
        total_1d_change += day_change
    
    summary = {
        "total_invested": round(total_invested, 2),
        "total_current": round(total_current, 2),
        "total_estimated_current": round(total_estimated_current, 2),
        "total_return": round(total_current - total_invested, 2),
        "total_return_pct": round(((total_current - total_invested) / total_invested * 100) if total_invested > 0 else 0, 2),
        "day_change": round(total_1d_change, 2),
        "day_change_pct": round((total_1d_change / total_current * 100) if total_current > 0 else 0, 2),
    }
    
    return {
        "status": "success",
        "user": user,
        "data": enriched,
        "summary": summary,
        "market_status": get_market_status(),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/api/portfolio/add")
async def api_add_to_portfolio(item: PortfolioAdd, authorization: Optional[str] = Header(None)):
    """Add a fund to the user's portfolio."""
    user = resolve_user(authorization)
    if not user:
        return {"status": "unauthenticated", "message": "Please log in to add funds to your portfolio"}
    result = add_to_portfolio(
        user_id=user["id"],
        scheme_code=item.scheme_code,
        scheme_name=item.scheme_name,
        units=item.units,
        avg_buy_nav=item.avg_buy_nav,
        invested_amount=item.invested_amount
    )
    return result


@app.delete("/api/portfolio/{scheme_code}")
async def api_remove_from_portfolio(scheme_code: str, authorization: Optional[str] = Header(None)):
    """Remove a fund from the user's portfolio (returns removed item for undo)."""
    user = resolve_user(authorization)
    if not user:
        return {"status": "unauthenticated", "message": "Please log in to remove funds from your portfolio"}
    return remove_from_portfolio(user["id"], scheme_code)


# --- Watchlist Routes ---

@app.get("/api/watchlist")
async def api_get_watchlist(authorization: Optional[str] = Header(None)):
    """Get user's watchlist with live estimations."""
    global _all_funds_cache, _index_data_cache
    
    user = resolve_user(authorization)
    if not user:
        return {"status": "unauthenticated", "data": []}
    watchlist = get_watchlist(user["id"])
    
    if not _all_funds_cache:
        _all_funds_cache = fetch_all_nav()
    
    index_changes = {ticker: data["change_pct"] for ticker, data in _index_data_cache.items()}
    
    enriched = []
    for item in watchlist:
        fund = _all_funds_cache.get(item["scheme_code"], {})
        estimation = estimate_nav_for_fund(fund, index_changes) if fund else None
        
        entry = {
            **item,
            "current_nav": fund.get("nav", 0),
            "estimation": estimation
        }
        enriched.append(entry)
        
    return {"status": "success", "data": enriched}


@app.post("/api/watchlist/add")
async def api_add_to_watchlist(item: WatchlistAdd, authorization: Optional[str] = Header(None)):
    """Add a fund to the user's watchlist."""
    user = resolve_user(authorization)
    if not user:
        return {"status": "unauthenticated", "message": "Please log in first"}
    return add_to_watchlist(user["id"], item.scheme_code, item.scheme_name)


@app.delete("/api/watchlist/{scheme_code}")
async def api_remove_from_watchlist(scheme_code: str, authorization: Optional[str] = Header(None)):
    """Remove a fund from the user's watchlist."""
    user = resolve_user(authorization)
    if not user:
        return {"status": "unauthenticated", "message": "Please log in first"}
    return remove_from_watchlist(user["id"], scheme_code)


@app.get("/api/refresh")
async def api_refresh_data():
    """Force refresh all data."""
    global _all_funds_cache, _index_data_cache
    
    _all_funds_cache = fetch_all_nav(force_refresh=True)
    _index_data_cache = fetch_all_indices()
    
    return {
        "status": "success",
        "funds_count": len(_all_funds_cache),
        "indices_count": len(_index_data_cache),
        "timestamp": datetime.now().isoformat()
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print("=" * 60)
    print("  📈 NAV Estimator - Live Mutual Fund NAV Tracker")
    print(f"  🌐 Running on port {port}")
    print("=" * 60)
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
