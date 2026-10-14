"""Family tenants, membership, encrypted cloud tokens and OAuth state."""
import os, sqlite3, secrets
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

DB_PATH = Path(os.getenv("DB_PATH", "data/archive.sqlite3"))
FERNET_KEY = os.getenv("FERNET_KEY", "").strip()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    return c

def cipher():
    if not FERNET_KEY:
        raise RuntimeError("FERNET_KEY is required for cloud-token storage")
    try: return Fernet(FERNET_KEY.encode())
    except Exception as e: raise RuntimeError("Invalid FERNET_KEY") from e

def init():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS families(
          id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
          owner_telegram_id INTEGER NOT NULL, yadisk_token_enc BLOB,
          yadisk_account_label TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS family_members(
          family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
          telegram_id INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','admin','member')),
          joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(family_id,telegram_id));
        CREATE INDEX IF NOT EXISTS family_members_user ON family_members(telegram_id);
        CREATE TABLE IF NOT EXISTS oauth_states(
          state TEXT PRIMARY KEY, family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
          telegram_id INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)

def create_family(name, owner_id):
    init()
    name = " ".join((name or "").split())[:80]
    if not name: raise ValueError("Введите название семьи")
    with connect() as c:
        cur = c.execute("INSERT INTO families(name,owner_telegram_id) VALUES(?,?)",(name,int(owner_id)))
        fid = cur.lastrowid
        c.execute("INSERT INTO family_members(family_id,telegram_id,role) VALUES(?,?,'owner')",(fid,int(owner_id)))
        return fid

def families_for_user(user_id):
    init()
    with connect() as c:
        return [dict(r) for r in c.execute("""SELECT f.id,f.name,m.role,f.yadisk_account_label
          FROM families f JOIN family_members m ON m.family_id=f.id
          WHERE m.telegram_id=? ORDER BY f.name""",(int(user_id),))]

def rename_family(fid, name, actor_id):
    name = " ".join((name or "").split())[:80]
    if not name: raise ValueError("Введите название архива")
    role = role_for_user(fid, actor_id)
    if role != "owner": raise PermissionError("Переименовывать архив может только владелец")
    with connect() as c:
        cur = c.execute("UPDATE families SET name=? WHERE id=?", (name, int(fid)))
        if cur.rowcount != 1: raise ValueError("Архив не найден")

def get_family(fid):
    init()
    with connect() as c:
        r=c.execute("SELECT * FROM families WHERE id=?",(int(fid),)).fetchone()
        return dict(r) if r else None

def role_for_user(fid,user_id):
    init()
    with connect() as c:
        r=c.execute("SELECT role FROM family_members WHERE family_id=? AND telegram_id=?",(int(fid),int(user_id))).fetchone()
        return r["role"] if r else None

def add_member(fid,user_id,role="member",actor_id=None):
    if role not in ("admin","member"): raise ValueError("Недопустимая роль")
    if role_for_user(fid,actor_id) not in ("owner","admin"): raise PermissionError("Нет прав приглашать участников")
    with connect() as c:
        c.execute("INSERT OR IGNORE INTO family_members(family_id,telegram_id,role) VALUES(?,?,?)",(int(fid),int(user_id),role))

def remove_member(fid,user_id,actor_id):
    if role_for_user(fid,actor_id) != "owner": raise PermissionError("Удалять участников может только владелец семьи")
    if int(user_id)==int(actor_id): raise ValueError("Нельзя удалить самого владельца")
    with connect() as c: c.execute("DELETE FROM family_members WHERE family_id=? AND telegram_id=?",(int(fid),int(user_id)))

def save_yadisk_token(fid,token,label=""):
    if not token: raise ValueError("Пустой токен")
    encrypted=cipher().encrypt(token.encode())
    with connect() as c:
        c.execute("UPDATE families SET yadisk_token_enc=?,yadisk_account_label=? WHERE id=?",(encrypted,(label or "")[:160],int(fid)))

def get_yadisk_token(fid):
    f=get_family(fid)
    if not f or not f.get("yadisk_token_enc"): return None
    try: return cipher().decrypt(f["yadisk_token_enc"]).decode()
    except InvalidToken as e: raise RuntimeError("Не удалось расшифровать токен; проверьте FERNET_KEY") from e

def create_oauth_state(fid,user_id):
    state=secrets.token_urlsafe(32)
    with connect() as c:
        c.execute("DELETE FROM oauth_states WHERE created_at < datetime('now','-15 minutes')")
        c.execute("INSERT INTO oauth_states(state,family_id,telegram_id) VALUES(?,?,?)",(state,int(fid),int(user_id)))
    return state

def consume_oauth_state(state):
    with connect() as c:
        row=c.execute("SELECT family_id,telegram_id,created_at FROM oauth_states WHERE state=?",(state,)).fetchone()
        if not row: return None
        c.execute("DELETE FROM oauth_states WHERE state=?",(state,))
        return dict(row)

def disk_connected(fid):
    f=get_family(fid)
    return bool(f and f.get("yadisk_token_enc"))
