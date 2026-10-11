"""Family-scoped SQLite index. Every query requires family_id."""
import json, os, sqlite3
from pathlib import Path
from datetime import datetime
from tenancy import connect, init as init_tenancy

def init():
    init_tenancy()
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS patients(
          id INTEGER PRIMARY KEY, family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
          name TEXT NOT NULL COLLATE NOCASE, UNIQUE(family_id,name));
        CREATE TABLE IF NOT EXISTS docs(
          id INTEGER PRIMARY KEY, family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
          patient TEXT NOT NULL COLLATE NOCASE, name TEXT, kind TEXT, date TEXT,
          remote TEXT, ocr_remote TEXT, text TEXT, keywords TEXT, digest TEXT, added TEXT,
          UNIQUE(family_id,patient,digest));
        CREATE INDEX IF NOT EXISTS docs_family_patient ON docs(family_id,patient,date);
        """)
init()

def add_patient(fid,name):
    name=" ".join((name or "").split())[:100]
    if not name: raise ValueError("Имя пациента не может быть пустым")
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO patients(family_id,name) VALUES(?,?)",(int(fid),name))

def patients(fid):
    with connect() as c:
        return [r["name"] for r in c.execute("SELECT name FROM patients WHERE family_id=? ORDER BY name",(int(fid),))]

def add_doc(fid,p,name,kind,date,remote,ocr_remote,text,keywords,digest):
    with connect() as c:
        cur=c.execute("""INSERT OR IGNORE INTO docs
        (family_id,patient,name,kind,date,remote,ocr_remote,text,keywords,digest,added)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (int(fid),p,name,kind,date,remote,ocr_remote,text,json.dumps(keywords,ensure_ascii=False),digest,datetime.now().isoformat()))
        return cur.rowcount==1

def search(fid,p,query="",limit=10):
    with connect() as c:
        rows=c.execute("SELECT * FROM docs WHERE family_id=? AND patient=? COLLATE NOCASE ORDER BY added DESC",(int(fid),p)).fetchall()
    terms=(query or "").lower().split()
    out=[]
    for row in rows:
        d=dict(row)
        blob=" ".join(str(d.get(k) or "") for k in ("name","kind","date","text","keywords")).lower()
        if not terms or all(t in blob for t in terms): out.append(d)
    return out[:max(1,min(int(limit),1000))]

def context(fid,p,query,limit=8):
    rows=search(fid,p,query,limit)
    return "\n\n---\n\n".join(
      f"Источник: {r['name']} | {r['kind']} | дата: {r['date']}\n{r['text'][:2500]}" for r in rows)

def history(fid,p):
    rows=search(fid,p,"",1000)
    rows.sort(key=lambda x:(x["date"] or "",x["added"] or ""))
    return "\n\n".join(f"{r['date']} — {r['kind']}\n{r['name']}\nОригинал: {r['remote']}\n{r['text'][:3500]}" for r in rows)

def document_count(fid,p):
    with connect() as c:
        r=c.execute("SELECT COUNT(*) n FROM docs WHERE family_id=? AND patient=?",(int(fid),p)).fetchone()
        return r["n"]
