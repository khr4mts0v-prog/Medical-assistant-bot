"""Family-scoped SQLite index. Every query requires family_id."""
import json, os, sqlite3, logging
from pathlib import Path
from datetime import datetime
from tenancy import connect, init as init_tenancy, cipher

def init():
    init_tenancy()
    # Preserve a previous single-family database instead of crashing on its old schema.
    # It is deliberately not auto-assigned to a family because ownership is unknown.
    with connect() as c:
        tables={r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "patients" in tables:
            cols={r["name"] for r in c.execute("PRAGMA table_info(patients)")}
            if "family_id" not in cols:
                c.execute("ALTER TABLE patients RENAME TO legacy_patients")
                if "docs" in tables:
                    c.execute("ALTER TABLE docs RENAME TO legacy_docs")
                logging.warning("Legacy single-family archive preserved as legacy_patients/legacy_docs; import only after assigning it to the correct family.")
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

def patient_by_id(fid, patient_id):
    with connect() as c:
        r=c.execute("SELECT name FROM patients WHERE family_id=? AND id=?",(int(fid),int(patient_id))).fetchone()
        return r["name"] if r else None

def patient_id(fid, name):
    with connect() as c:
        r=c.execute("SELECT id FROM patients WHERE family_id=? AND name=? COLLATE NOCASE",(int(fid),name)).fetchone()
        return r["id"] if r else None

def document_exists(fid, patient, digest):
    with connect() as c:
        row=c.execute("SELECT 1 FROM docs WHERE family_id=? AND patient=? COLLATE NOCASE AND digest=?",
                      (int(fid),patient,digest)).fetchone()
        return row is not None

def add_doc(fid,p,name,kind,date,remote,ocr_remote,text,keywords,digest):
    with connect() as c:
        cur=c.execute("""INSERT OR IGNORE INTO docs
        (family_id,patient,name,kind,date,remote,ocr_remote,text,keywords,digest,added)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (int(fid),p,name,kind,date,remote,ocr_remote,cipher().encrypt((text or "").encode("utf-8")),
         cipher().encrypt(json.dumps(keywords,ensure_ascii=False).encode("utf-8")),digest,datetime.now().isoformat()))
        return cur.rowcount==1

def get_doc(fid, doc_id):
    """Return one document only when it belongs to the requested family."""
    with connect() as c:
        row=c.execute("SELECT * FROM docs WHERE family_id=? AND id=?",(int(fid),int(doc_id))).fetchone()
    if not row:
        return None
    d=dict(row)
    try:
        d["text"]=cipher().decrypt(d["text"]).decode("utf-8") if d.get("text") else ""
        raw_keywords=cipher().decrypt(d["keywords"]).decode("utf-8") if d.get("keywords") else "[]"
        d["keywords"]=json.loads(raw_keywords)
    except Exception:
        logging.exception("Cannot decrypt family document index entry")
        return None
    return d

def search(fid,p,query="",limit=10):
    with connect() as c:
        rows=c.execute("SELECT * FROM docs WHERE family_id=? AND patient=? COLLATE NOCASE ORDER BY added DESC",(int(fid),p)).fetchall()
    terms=(query or "").lower().split()
    out=[]
    for row in rows:
        d=dict(row)
        try:
            d["text"]=cipher().decrypt(d["text"]).decode("utf-8") if d.get("text") else ""
            raw_keywords=cipher().decrypt(d["keywords"]).decode("utf-8") if d.get("keywords") else "[]"
            d["keywords"]=json.loads(raw_keywords)
        except Exception:
            logging.exception("Cannot decrypt family document index entry")
            continue
        blob=" ".join(str(d.get(k) or "") for k in ("name","kind","date","text","keywords")).lower()
        if not terms or any(t in blob for t in terms): out.append(d)
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
