import sys
sys.path.insert(0, '.')
from backend.database.engine import DB_PATH
import sqlite3

conn = sqlite3.connect(DB_PATH)
try:
    conn.execute("UPDATE paper_questions SET user_id = COALESCE((SELECT papers.user_id FROM papers WHERE papers.id = paper_questions.paper_id), '') WHERE user_id IS NULL OR user_id = ''")
    print("Success")
except Exception as e:
    print("Error:", e)
    # Check if there are triggers on paper_questions
    triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'paper_questions'").fetchall()
    print("Triggers on paper_questions:", triggers)
    # Check on papers
    triggers = conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'papers'").fetchall()
    print("Triggers on papers:", triggers)
