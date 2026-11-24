"""
AMFI NAV Data Service
Fetches latest NAV data for all mutual funds from AMFI India
"""
import requests
import json
import os
import re
import time
from datetime import datetime, timedelta
from typing import Optional

AMFI_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
NAV_CACHE_FILE = os.path.join(CACHE_DIR, "nav_all.json")
FUND_LIST_CACHE = os.path.join(CACHE_DIR, "fund_list.json")


def ensure_cache_dir():
    os.makedirs(CACHE_DIR, exist_ok=True)


def parse_amfi_nav_data(raw_text: str) -> dict:
    """
    Parse the AMFI NAV text file into structured data.
    Format:
    Scheme Code;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
    Grouped under AMC headers.
    """
    funds = {}
    current_amc = ""
    current_category = ""

    lines = raw_text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if it's a header line (AMC name or category)
        if "Mutual Fund" in line and ";" not in line:
            current_amc = line.strip()
            continue
        
        # Category headers (like "Open Ended Schemes(Equity Scheme - Large Cap Fund)")
        if line.startswith("Open Ended") or line.startswith("Close Ended") or line.startswith("Interval"):
            current_category = line.strip()
            continue

        # Skip the column header line
        if line.startswith("Scheme Code"):
            continue

        parts = line.split(";")
        if len(parts) >= 5:
            try:
                scheme_code = parts[0].strip()
                isin_payout = parts[1].strip() if len(parts) > 1 else ""
                isin_reinvest = parts[2].strip() if len(parts) > 2 else ""
                
                # AMFI format varies:
                # Old: SchemeCode;ISIN1;ISIN2;SchemeName;NAV;Date
                # New: SchemeCode;ISIN1;ISIN2;SchemeName;PlanType;OptionType;NAV;Date
                # Detect by trying to parse NAV from different positions
                
                nav = None
                nav_date = ""
                scheme_name = parts[3].strip() if len(parts) > 3 else ""
                
                if len(parts) >= 8:
                    # New format with Plan and Option columns
                    plan = parts[4].strip() if len(parts) > 4 else ""
                    option = parts[5].strip() if len(parts) > 5 else ""
                    nav_str = parts[6].strip() if len(parts) > 6 else ""
                    nav_date = parts[7].strip() if len(parts) > 7 else ""
                    
                    # Build full scheme name with plan info
                    if plan:
                        scheme_name = f"{scheme_name} - {plan}"
                    if option:
                        scheme_name = f"{scheme_name} - {option}"
                    
                    try:
                        nav = float(nav_str) if nav_str and nav_str != "N.A." else None
                    except ValueError:
                        nav = None
                
                elif len(parts) >= 6:
                    # Old format OR partial new format
                    nav_str = parts[4].strip()
                    nav_date = parts[5].strip() if len(parts) > 5 else ""
                    
                    try:
                        nav = float(nav_str) if nav_str and nav_str != "N.A." else None
                    except ValueError:
                        # parts[4] might be plan type, not NAV
                        # Try parts[5] and parts[6]
                        if len(parts) >= 7:
                            try:
                                nav = float(parts[5].strip()) if parts[5].strip() and parts[5].strip() != "N.A." else None
                                nav_date = parts[6].strip() if len(parts) > 6 else ""
                                plan = parts[4].strip()
                                if plan:
                                    scheme_name = f"{scheme_name} - {plan}"
                            except ValueError:
                                nav = None
                        else:
                            nav = None

                funds[scheme_code] = {
                    "scheme_code": scheme_code,
                    "isin_payout": isin_payout,
                    "isin_reinvest": isin_reinvest,
                    "scheme_name": scheme_name,
                    "nav": nav,
                    "nav_date": nav_date,
                    "amc": current_amc,
                    "category": current_category,
                    "_norm_text": normalize_search_text(f"{scheme_name} {current_amc}"),
                }
            except (IndexError, ValueError):
                continue

    return funds


def fetch_all_nav(force_refresh: bool = False) -> dict:
    """
    Fetch all NAV data from AMFI. Uses cache if available and fresh (< 1 hour).
    """
    ensure_cache_dir()

    # Check cache
    if not force_refresh and os.path.exists(NAV_CACHE_FILE):
        try:
            with open(NAV_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            cache_time = cached.get("_cache_time", 0)
            # Cache valid for 1 hour
            if time.time() - cache_time < 3600:
                funds = cached.get("funds", {})
                # Ensure _norm_text is present
                for f in funds.values():
                    if not f.get("_norm_text"):
                        f["_norm_text"] = normalize_search_text(f"{f.get('scheme_name', '')} {f.get('amc', '')}")
                return funds
        except (json.JSONDecodeError, KeyError):
            pass

    # Fetch fresh data
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetching NAV data from AMFI...")
        response = requests.get(AMFI_NAV_URL, timeout=30)
        response.raise_for_status()
        
        funds = parse_amfi_nav_data(response.text)
        
        # Save to cache
        cache_data = {
            "_cache_time": time.time(),
            "_fetch_time": datetime.now().isoformat(),
            "_count": len(funds),
            "funds": funds
        }
        with open(NAV_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False)
        
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Fetched {len(funds)} fund NAVs")
        return funds

    except Exception as e:
        print(f"Error fetching AMFI data: {e}")
        # Return cached data if available
        if os.path.exists(NAV_CACHE_FILE):
            with open(NAV_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            return cached.get("funds", {})
        return {}


# --- Query Normalization & Smart Search ---
QUERY_ALIASES = {
    "ppfas": ["parag", "parikh"],
    "dir": ["direct"],
    "gr": ["growth"],
    "reg": ["regular"],
    "div": ["idcw", "dividend"],
    "nifty50": ["nifty", "50"],
    "sensex": ["sensex"],
}

CATEGORY_SYNONYMS = {
    "flexicap": "flexi cap",
    "smallcap": "small cap",
    "midcap": "mid cap",
    "largecap": "large cap",
    "multicap": "multi cap",
    "bluechip": "blue chip",
}

STOP_WORDS = {"fund", "scheme", "mutual", "mf"}


def normalize_search_text(text: str) -> str:
    """Normalize text by standardizing synonyms and removing special characters."""
    if not text:
        return ""
    text = text.lower()
    for k, v in CATEGORY_SYNONYMS.items():
        text = text.replace(k, v)
    text = re.sub(r'[^a-zA-Z0-9\s]', ' ', text)
    return ' '.join(text.split())


def search_funds(query: str, all_funds: Optional[dict] = None) -> list:
    """
    Smart fuzzy / token-based search for mutual funds across all AMCs.
    Supports queries with or without hyphens, partial words, 'direct', 'growth',
    acronyms like 'ppfas', etc.
    """
    if all_funds is None:
        all_funds = fetch_all_nav()
    
    q_norm = normalize_search_text(query)
    raw_tokens = q_norm.split()
    if not raw_tokens:
        return []
    
    # Expand aliases in user query (e.g., ppfas -> parag parikh)
    tokens = []
    for t in raw_tokens:
        if t in QUERY_ALIASES:
            tokens.extend(QUERY_ALIASES[t])
        else:
            tokens.append(t)
            
    # Informative tokens (ignore generic terms like 'fund' unless that's all that was typed)
    info_tokens = [t for t in tokens if t not in STOP_WORDS]
    if not info_tokens:
        info_tokens = tokens
        
    wants_direct = "direct" in tokens
    wants_regular = "regular" in tokens
    wants_growth = "growth" in tokens
    wants_idcw = "idcw" in tokens or "dividend" in tokens
    
    q_exact = query.strip().lower()
    scored = []
    
    for code, fund in all_funds.items():
        if code.startswith("_"):
            continue
            
        scode = fund.get("scheme_code", "")
        sname = fund.get("scheme_name", "")
        isin = fund.get("isin_payout", "")
        amc = fund.get("amc", "")
        
        # Exact match on scheme code or ISIN
        if q_exact == scode.lower() or (isin and q_exact == isin.lower()):
            scored.append((10000, fund))
            continue
            
        # Precomputed or cached normalized text
        norm_text = fund.get("_norm_text")
        if not norm_text:
            norm_text = normalize_search_text(f"{sname} {amc}")
            fund["_norm_text"] = norm_text
            
        target_words = norm_text.split()
        
        matched_info = 0
        exact_token_matches = 0
        for tok in info_tokens:
            for w in target_words:
                if w == tok:
                    matched_info += 1
                    exact_token_matches += 1
                    break
                elif w.startswith(tok) or (len(tok) >= 4 and tok in w):
                    matched_info += 1
                    break
                    
        total_info = len(info_tokens)
        required = total_info if total_info <= 3 else (total_info - 1 if total_info <= 5 else total_info - 2)
        if matched_info < required:
            continue
            
        score = matched_info * 120 + exact_token_matches * 50
        
        # All tokens present bonus
        if matched_info == total_info:
            score += 500
            
        # Continuous substring bonus
        if q_norm in norm_text:
            score += 800
            
        # Leading word bonus
        if target_words and info_tokens and (target_words[0] == info_tokens[0] or target_words[0].startswith(info_tokens[0])):
            score += 250
            
        # Direct vs Regular preference
        has_direct = "direct" in target_words
        has_regular = "regular" in target_words
        if wants_direct:
            if has_direct:
                score += 600
            if has_regular:
                score -= 400
        elif wants_regular:
            if has_regular:
                score += 600
            if has_direct:
                score -= 400
        else:
            if has_direct:
                score += 60
                
        # Growth vs IDCW preference
        has_growth = "growth" in target_words
        has_idcw = "idcw" in target_words or "dividend" in target_words
        if wants_growth:
            if has_growth:
                score += 600
            if has_idcw:
                score -= 400
        elif wants_idcw:
            if has_idcw:
                score += 600
            if has_growth:
                score -= 400
        else:
            if has_growth:
                score += 120
                
        # Length penalty to prioritize clean concise scheme names
        score -= min(len(sname) * 0.1, 40)
        scored.append((score, fund))
        
    scored.sort(key=lambda x: x[0], reverse=True)
    return [fund for score, fund in scored[:50]]


def get_fund_nav(scheme_code: str, all_funds: Optional[dict] = None) -> Optional[dict]:
    """Get NAV for a specific fund by scheme code."""
    if all_funds is None:
        all_funds = fetch_all_nav()
    return all_funds.get(scheme_code)


def get_fund_nav_history(scheme_code: str) -> list:
    """
    Get historical NAV data from mfapi.in (free community API).
    Returns list of {date, nav} dicts.
    """
    try:
        url = f"https://api.mfapi.in/mf/{scheme_code}"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        nav_data = []
        for entry in data.get("data", []):
            try:
                nav_data.append({
                    "date": entry["date"],
                    "nav": float(entry["nav"])
                })
            except (ValueError, KeyError):
                continue
        
        return nav_data
    except Exception as e:
        print(f"Error fetching NAV history for {scheme_code}: {e}")
        return []
