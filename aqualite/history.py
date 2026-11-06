"""Local dictation history (SQLite), like Wispr Flow's flow.sqlite - but it never leaves your PC."""
import os
import sqlite3
import threading
import time

from .config import data_dir

PATH = os.path.join(data_dir(), "history.sqlite")
_lock = threading.Lock()
_db = None


def db():
    global _db
    if _db is None:
        _db = sqlite3.connect(PATH, check_same_thread=False)
        _db.execute("""CREATE TABLE IF NOT EXISTS dictations (
            id INTEGER PRIMARY KEY, ts REAL, app TEXT, title TEXT, mode TEXT, raw TEXT, final TEXT,
            seconds REAL, words INTEGER, engine TEXT, latency REAL, status TEXT)""")
        _db.commit()
    return _db


def add(**row):
    row.setdefault("ts", time.time())
    cols = ",".join(row)
    with _lock:
        db().execute(f"INSERT INTO dictations ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
        db().commit()


def recent(limit=300, query=""):
    sql = "SELECT id, ts, app, mode, final, raw, seconds, words, engine, latency, status FROM dictations"
    args = []
    if query:
        sql += " WHERE final LIKE ? OR raw LIKE ? OR app LIKE ?"
        args = [f"%{query}%"] * 3
    sql += " ORDER BY id DESC LIMIT ?"
    with _lock:
        return db().execute(sql, args + [limit]).fetchall()


def last_text():
    with _lock:
        r = db().execute("SELECT final FROM dictations WHERE final != '' ORDER BY id DESC LIMIT 1").fetchone()
    return r[0] if r else ""


def stats():
    with _lock:
        n, words, secs = db().execute(
            "SELECT COUNT(*), COALESCE(SUM(words),0), COALESCE(SUM(seconds),0) FROM dictations WHERE final != ''"
        ).fetchone()
        week = db().execute("SELECT COALESCE(SUM(words),0) FROM dictations WHERE ts > ?",
                            (time.time() - 7 * 86400,)).fetchone()[0]
    wpm = words / (secs / 60) if secs > 5 else 0
    typing_minutes = words / 40  # average typing speed
    saved = max(0.0, typing_minutes - secs / 60)
    return {"sessions": n, "words": words, "wpm": wpm, "minutes_saved": saved, "week_words": week}


def delete(row_id):
    with _lock:
        db().execute("DELETE FROM dictations WHERE id = ?", (row_id,))
        db().commit()


def clear():
    with _lock:
        db().execute("DELETE FROM dictations")
        db().commit()
