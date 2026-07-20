import sqlite3
from pathlib import Path

DB_PATH = Path("output/scrib.db")

def check_db():
    if not DB_PATH.exists():
        print("Database file does not exist yet.")
        return
        
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("--- GUIDES ---")
    cursor.execute("SELECT * FROM guides")
    guides = cursor.fetchall()
    for g in guides:
        print(f"Guide ID: {g['id']}, Title: {g['title']}")
        
    print("\n--- STEPS ---")
    cursor.execute("SELECT * FROM steps")
    steps = cursor.fetchall()
    for s in steps:
        print(f"Step ID: {s['id']}, Guide ID: {s['guide_id']}, Caption: {s['caption'][:30]}, URL: {s['screenshot_url']}, X: {s['click_x_percent']}, Y: {s['click_y_percent']}, IsAnnotated: {s.get('is_annotated')}")

if __name__ == '__main__':
    check_db()
