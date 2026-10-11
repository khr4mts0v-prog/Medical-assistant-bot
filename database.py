import json, os, sqlite3
from pathlib import Path
from datetime import datetime

DB = Path(os.getenv("DB_PATH", "data/archive.sqlite3"))
DB.parent.mkdir(parents=True, exist_ok=True)

def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

with connect() as db:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS patients(id INTEGER PRIMARY KEY, name TEXT UNIQUE COLLATE NOCASE);
    CREATE TABLE IF NOT EXISTS docs(
      id INTEGER PRIMARY KEY, patient TEXT COLLATE NOCASE, name TEXT, kind TEXT, date TEXT,
      remote TEXT, ocr_remote TEXT, text TEXT, keywords TEXT, digest TEXT, added TEXT,
      UNIQUE(patient,digest));
    CREATE INDEX IF NOT EXISTS docs_patient ON docs(patient,date);
    """)

def add_patient(name):
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO patients(name) VALUES(?)", (name.strip(),))

def patients():
    with connect() as db:
        return [r["name"] for r in db.execute("SELECT name FROM patients ORDER BY name")]

def add_doc(p, name, kind, date, remote, ocr_remote, text, keywords, digest):
    with connect() as db:
        cur = db.execute("""INSERT OR IGNORE INTO docs
        (patient,name,kind,date,remote,ocr_remote,text,keywords,digest,added)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (p,name,kind,date,remote,ocr_remote,text,json.dumps(keywords,ensure_ascii=False),digest,datetime.now().isoformat()))
        return cur.rowcount == 1

def search(p, query="", limit=10):
    with connect() as db:
        rows = db.execute("SELECT * FROM docs WHERE patient=? COLLATE NOCASE ORDER BY added DESC", (p,)).fetchall()
    terms = query.lower().split()
    rows = [dict(r) for r in rows if not terms or any(t in (r["name"]+" "+r["kind"]+" "+r["date"]+" "+r["text"]+" "+r["keywords"]).lower() for t in terms)]
    return rows[:limit]

def context(p, query, limit=8):
    rows = search(p, query, limit)
    return "\n\n---\n\n".join(
      f"Источник: {r['name']} | {r['kind']} | дата: {r['date']} | Я.Диск: {r['remote']}\n{r['text'][:2500]}"
      for r in rows)
    
def history(p):
    rows = search(p, "", 1000)
    return "\n\n".join(f"{r['date']} — {r['kind']}\n{r['name']}\nОригинал: {r['remote']}\n{r['text'][:3500]}" for r in sorted(rows,key=lambda x:x['date']))
