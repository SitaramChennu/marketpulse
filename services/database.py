"""
Portfolio Database Service
Multi-user SQLite storage for user mutual fund portfolios, watchlists, and authentication.
"""
import sqlite3
import hashlib
import secrets
import os
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DB_DIR, "portfolio.db")


def get_db():
    """Get database connection."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def hash_password(password: str, salt: str) -> str:
    """Hash password using sha256 with salt."""
    return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()


def init_db():
    """Initialize database tables with multi-user support."""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Sessions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # 3. Portfolio table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            scheme_code TEXT NOT NULL,
            scheme_name TEXT NOT NULL,
            units REAL NOT NULL,
            avg_buy_nav REAL,
            invested_amount REAL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, scheme_code),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # 4. Watchlist table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            scheme_code TEXT NOT NULL,
            scheme_name TEXT NOT NULL,
            added_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, scheme_code),
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)
    
    # Migration: check if user_id exists in portfolio
    cursor.execute("PRAGMA table_info(portfolio)")
    cols = [r[1] for r in cursor.fetchall()]
    if "user_id" not in cols:
        cursor.execute("ALTER TABLE portfolio ADD COLUMN user_id INTEGER DEFAULT 1")
        
    cursor.execute("PRAGMA table_info(watchlist)")
    wcols = [r[1] for r in cursor.fetchall()]
    if "user_id" not in wcols:
        cursor.execute("ALTER TABLE watchlist ADD COLUMN user_id INTEGER DEFAULT 1")
        
    # Create default user (id=1) if empty
    cursor.execute("SELECT * FROM users WHERE id = 1")
    if not cursor.fetchone():
        salt = secrets.token_hex(16)
        pwd_hash = hash_password("password", salt)
        cursor.execute(
            "INSERT INTO users (id, username, password_hash, salt) VALUES (1, ?, ?, ?)",
            ("sitaram", pwd_hash, salt)
        )
        
    conn.commit()
    conn.close()
    print("Database initialized with multi-user support.")


# --- Authentication Functions ---

def register_user(username: str, password: str) -> Tuple[Optional[dict], Optional[str]]:
    """Register a new user account."""
    username = username.strip().lower()
    if len(username) < 3:
        return None, "Username must be at least 3 characters"
    if len(password) < 4:
        return None, "Password must be at least 4 characters"
        
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        salt = secrets.token_hex(16)
        pwd_hash = hash_password(password, salt)
        cursor.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (username, pwd_hash, salt)
        )
        user_id = cursor.lastrowid
        conn.commit()
        
        # Create session token
        token = secrets.token_hex(32)
        cursor.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        conn.commit()
        
        return {"id": user_id, "username": username, "token": token}, None
    except sqlite3.IntegrityError:
        return None, "Username already exists. Please choose a different one or login."
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()


def login_user(username: str, password: str) -> Tuple[Optional[dict], Optional[str]]:
    """Authenticate user and return a session token."""
    username = username.strip().lower()
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if not user:
            return None, "User not found. Please sign up."
            
        expected_hash = hash_password(password, user["salt"])
        if expected_hash != user["password_hash"]:
            return None, "Incorrect password"
            
        token = secrets.token_hex(32)
        cursor.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
        conn.commit()
        
        return {"id": user["id"], "username": user["username"], "token": token}, None
    except Exception as e:
        return None, str(e)
    finally:
        conn.close()


def get_user_from_token(token: Optional[str]) -> Optional[dict]:
    """Retrieve user by session token. Returns None if invalid or missing."""
    if not token:
        return None
        
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT u.id, u.username FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ?
        """, (token,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception:
        return None
    finally:
        conn.close()


def logout_user(token: str):
    """Delete session token."""
    if not token:
        return
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


# --- Portfolio Functions (Scoped by user_id) ---

def add_to_portfolio(user_id: int, scheme_code: str, scheme_name: str, units: float,
                     avg_buy_nav: float = None, invested_amount: float = None) -> dict:
    """Add or update a fund in the user's portfolio."""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        now_str = datetime.now().isoformat()
        cursor.execute("""
            INSERT INTO portfolio (user_id, scheme_code, scheme_name, units, avg_buy_nav, invested_amount, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, scheme_code) DO UPDATE SET
                scheme_name = excluded.scheme_name,
                units = excluded.units,
                avg_buy_nav = excluded.avg_buy_nav,
                invested_amount = excluded.invested_amount,
                updated_at = excluded.updated_at
        """, (user_id, scheme_code, scheme_name, units, avg_buy_nav, invested_amount, now_str))
            
        conn.commit()
        return {"status": "success", "scheme_code": scheme_code, "message": "Fund added/updated"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def remove_from_portfolio(user_id: int, scheme_code: str) -> dict:
    """Remove a fund from the user's portfolio and return the removed data for undo."""
    conn = get_db()
    cursor = conn.cursor()
    
    # First get the item details so caller can undo if needed
    cursor.execute(
        "SELECT * FROM portfolio WHERE user_id = ? AND scheme_code = ?",
        (user_id, scheme_code)
    )
    item = cursor.fetchone()
    
    if item:
        removed_data = dict(item)
        cursor.execute("DELETE FROM portfolio WHERE id = ?", (removed_data["id"],))
        conn.commit()
        result = {"status": "success", "message": "Fund removed", "removed_item": removed_data}
    else:
        result = {"status": "error", "message": "Fund not found in portfolio"}
        
    conn.close()
    return result


def get_portfolio(user_id: int) -> List[dict]:
    """Get all funds in the user's portfolio."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM portfolio WHERE user_id = ? ORDER BY scheme_name", (user_id,))
    rows = cursor.fetchall()
    
    portfolio = [dict(row) for row in rows]
    conn.close()
    return portfolio


# --- Watchlist Functions (Scoped by user_id) ---

def add_to_watchlist(user_id: int, scheme_code: str, scheme_name: str) -> dict:
    """Add a fund to the user's watchlist."""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO watchlist (user_id, scheme_code, scheme_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, scheme_code) DO UPDATE SET
                scheme_name = excluded.scheme_name
        """, (user_id, scheme_code, scheme_name))
        conn.commit()
        return {"status": "success", "message": "Added to watchlist"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()


def remove_from_watchlist(user_id: int, scheme_code: str) -> dict:
    """Remove a fund from the user's watchlist."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM watchlist WHERE user_id = ? AND scheme_code = ?", (user_id, scheme_code))
    conn.commit()
    conn.close()
    return {"status": "success"}


def get_watchlist(user_id: int) -> List[dict]:
    """Get all watchlist items for user."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM watchlist WHERE user_id = ? ORDER BY scheme_name", (user_id,))
    rows = cursor.fetchall()
    watchlist = [dict(row) for row in rows]
    conn.close()
    return watchlist


# Initialize DB on import
init_db()
