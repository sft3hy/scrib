import sqlite3
import os
import uuid
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_PATH = Path("output/scrib.db")

def get_db_connection():
    """Get a connection to the SQLite database. Creates directory if missing."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize SQLite database tables and seed mock data."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        onboarding_completed BOOLEAN DEFAULT 0,
        onboarding_reason TEXT
    )
    """)
    
    # 2. Guides Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS guides (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        title TEXT DEFAULT 'Untitled Guide',
        description TEXT,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
    )
    """)
    
    # 3. Steps Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS steps (
        id TEXT PRIMARY KEY,
        guide_id TEXT,
        order_index INTEGER,
        caption TEXT,
        screenshot_url TEXT,
        click_x_percent REAL,
        click_y_percent REAL,
        FOREIGN KEY (guide_id) REFERENCES guides (id) ON DELETE CASCADE
    )
    """)
    
    # Safely add new columns to steps table for action annotations if they don't exist
    try:
        cursor.execute("ALTER TABLE steps ADD COLUMN click_width_percent REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE steps ADD COLUMN click_height_percent REAL DEFAULT 0.0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE steps ADD COLUMN is_typing BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE steps ADD COLUMN is_annotated BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    
    # Seed mock user if no users exist
    cursor.execute("SELECT COUNT(*) as count FROM users")
    if cursor.fetchone()["count"] == 0:
        cursor.execute(
            "INSERT INTO users (email, onboarding_completed, onboarding_reason) VALUES (?, ?, ?)",
            ("user@example.com", 0, None)
        )
        
    conn.commit()
    conn.close()

# --- Users functions ---

def get_user_by_id(user_id: int = 1) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return {}

def update_user_onboarding(user_id: int, completed: bool, reason: Optional[str]) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET onboarding_completed = ?, onboarding_reason = ? WHERE id = ?",
        (1 if completed else 0, reason, user_id)
    )
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

# --- Guides functions ---

def create_guide(user_id: int, title: str, description: Optional[str] = None) -> str:
    guide_id = str(uuid.uuid4())
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO guides (id, user_id, title, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (guide_id, user_id, title, description, now, now)
    )
    conn.commit()
    conn.close()
    return guide_id

def get_guides(user_id: int = 1) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guides WHERE user_id = ? ORDER BY updated_at DESC", (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_guide_by_id(guide_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM guides WHERE id = ?", (guide_id,))
    guide_row = cursor.fetchone()
    if not guide_row:
        conn.close()
        return None
    
    cursor.execute("SELECT * FROM steps WHERE guide_id = ? ORDER BY order_index ASC", (guide_id,))
    step_rows = cursor.fetchall()
    conn.close()
    
    guide_data = dict(guide_row)
    guide_data["steps"] = [dict(s) for s in step_rows]
    return guide_data

def update_guide(guide_id: str, title: str, description: Optional[str]) -> bool:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE guides SET title = ?, description = ?, updated_at = ? WHERE id = ?",
        (title, description, now, guide_id)
    )
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

def delete_guide(guide_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    # Cascading deletes are on, but SQLite foreign key support must be enabled or done manually.
    # To be safe, we delete steps manually first.
    cursor.execute("DELETE FROM steps WHERE guide_id = ?", (guide_id,))
    cursor.execute("DELETE FROM guides WHERE id = ?", (guide_id,))
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

# --- Steps functions ---

def create_step(
    guide_id: str,
    order_index: int,
    caption: str,
    screenshot_url: str,
    click_x_percent: float,
    click_y_percent: float,
    click_width_percent: float = 0.0,
    click_height_percent: float = 0.0,
    is_typing: bool = False,
    is_annotated: bool = False
) -> str:
    step_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO steps (
            id, guide_id, order_index, caption, screenshot_url, 
            click_x_percent, click_y_percent, click_width_percent, click_height_percent, 
            is_typing, is_annotated
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            step_id, guide_id, order_index, caption, screenshot_url, 
            click_x_percent, click_y_percent, click_width_percent, click_height_percent, 
            1 if is_typing else 0, 1 if is_annotated else 0
        )
    )
    # Also update updated_at on the parent guide
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE guides SET updated_at = ? WHERE id = ?", (now, guide_id))
    conn.commit()
    conn.close()
    return step_id

def update_step(step_id: str, caption: str, order_index: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE steps SET caption = ?, order_index = ? WHERE id = ?",
        (caption, order_index, step_id)
    )
    conn.commit()
    success = cursor.rowcount > 0
    conn.close()
    return success

def delete_step(step_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    # Find guide_id to fix other order_indexes and update timestamp
    cursor.execute("SELECT guide_id, order_index FROM steps WHERE id = ?", (step_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False
    
    guide_id = row["guide_id"]
    deleted_idx = row["order_index"]
    
    cursor.execute("DELETE FROM steps WHERE id = ?", (step_id,))
    
    # Adjust order_indexes for remaining steps
    cursor.execute("SELECT id, order_index FROM steps WHERE guide_id = ? ORDER BY order_index ASC", (guide_id,))
    remaining_steps = cursor.fetchall()
    for new_idx, step_row in enumerate(remaining_steps):
        cursor.execute("UPDATE steps SET order_index = ? WHERE id = ?", (new_idx, step_row["id"]))
        
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE guides SET updated_at = ? WHERE id = ?", (now, guide_id))
    
    conn.commit()
    conn.close()
    return True
