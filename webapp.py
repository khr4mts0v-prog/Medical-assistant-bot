"""Test web interface for Medical Archive. MUST be exposed only behind HTTPS."""
import base64, hashlib, hmac, html, logging, os, tempfile, threading, time, secrets
from pathlib import Path
from urllib.parse import urlencode
import requests
from fastapi import FastAPI, Depends, File, Form, HTTPException, UploadFile, Request
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db, tenancy
from cloud import YaDiskClient
from local_storage import save_file as save_local_file
from ocr import ocr_file
from AIAnalise import analyze_document, extract_keywords, classify_with_ai
from utils import format_filename, normalize_extension, parse_date_from_text, safe_name
from document_metadata import extract_registered_patient, extract_patient_birth_date

app=FastAPI(title="Medical Archive", docs_url=None, redoc_url=None)
from react_ui import install_react_ui
install_react_ui(app)

@app.get("/manifest.webmanifest")
def pwa_manifest():
    return Response(
        '{"name":"Медицинский архив","short_name":"Медархив","description":"Личный семейный архив медицинских документов","lang":"ru","start_url":"/app","scope":"/","display":"standalone","background_color":"#f2f6ff","theme_color":"#0755e8","icons":[{"src":"/apple-touch-icon.png","sizes":"180x180","type":"image/png","purpose":"any"},{"src":"/app-icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}',
        media_type="application/manifest+json",
        headers={"Cache-Control":"no-cache"},
    )

@app.get("/app-icon.svg")
def pwa_icon():
    icon_path=Path(__file__).resolve().parent/"docs"/"assets"/"medical-assistant-icon-concept.svg"
    if not icon_path.is_file():
        raise HTTPException(500,"Approved PWA icon asset is missing")
    return Response(icon_path.read_text(encoding="utf-8"),media_type="image/svg+xml",headers={"Cache-Control":"public, max-age=86400"})

@app.get("/apple-touch-icon.png")
def pwa_apple_touch_icon():
    # PNG rendition of the approved blue/white headset-stethoscope concept for iOS.
    from io import BytesIO
    from PIL import Image, ImageDraw
    image=Image.new("RGB",(180,180))
    pixels=image.load()
    for y in range(180):
        for x in range(180):
            t=(x+y)/358
            pixels[x,y]=(int(22*(1-t)+7*t),int(139*(1-t)+85*t),int(250*(1-t)+232*t))
    draw=ImageDraw.Draw(image)
    white="#ffffff"
    draw.arc((37,18,143,108),180,360,fill=white,width=9)
    draw.rounded_rectangle((30,65,53,112),radius=10,fill=white)
    draw.rounded_rectangle((127,65,150,112),radius=10,fill=white)
    draw.line([(42,98),(42,116),(55,132),(76,141),(88,141),(88,151)],fill=white,width=8)
    draw.line([(138,98),(138,113),(127,126),(111,133)],fill=white,width=8)
    draw.line([(111,133),(103,137)],fill=white,width=8)
    draw.ellipse((73,138,103,168),outline=white,width=7)
    draw.ellipse((84,149,92,157),fill=white)
    buffer=BytesIO()
    image.save(buffer,format="PNG",optimize=True)
    return Response(buffer.getvalue(),media_type="image/png",headers={"Cache-Control":"public, max-age=604800"})


@app.get("/sw.js")
def pwa_service_worker():
    # Deliberately network-only: never cache private medical records or OCR text.
    script='self.addEventListener("install",e=>self.skipWaiting());self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));self.addEventListener("fetch",e=>{if(e.request.method!=="GET")return;e.respondWith(fetch(e.request));});'
    return Response(script,media_type="application/javascript",headers={"Cache-Control":"no-cache","Service-Worker-Allowed":"/"})
security=HTTPBasic(auto_error=False)
SESSION_COOKIE_NAME="medical_archive_session"
SESSION_MAX_AGE=max(300,min(2592000,int(os.getenv("WEB_SESSION_MAX_AGE","604800"))))

def _session_signing_key():
    secret=os.getenv("WEB_SESSION_SECRET","").strip()
    return secret.encode("utf-8") if len(secret)>=32 else None

def _make_session(uid, expires_at=None):
    key=_session_signing_key()
    if not key:
        raise RuntimeError("WEB_SESSION_SECRET must contain at least 32 characters")
    expiry=int(expires_at if expires_at is not None else time.time()+SESSION_MAX_AGE)
    payload=f"{int(uid)}:{expiry}:{secrets.token_urlsafe(18)}".encode("utf-8")
    encoded=base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature=hmac.new(key,encoded.encode("ascii"),hashlib.sha256).hexdigest()
    return encoded+"."+signature

def _read_session(token):
    key=_session_signing_key()
    if not key or not token or len(token)>2048:
        return None
    try:
        encoded,signature=token.rsplit(".",1)
        expected=hmac.new(key,encoded.encode("ascii"),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):
            return None
        payload=base64.urlsafe_b64decode(encoded + "="*((4-len(encoded)%4)%4)).decode("utf-8")
        uid,expiry,_nonce=payload.split(":",2)
        uid=int(uid); expiry=int(expiry)
        if uid==0 or expiry<=int(time.time()) or expiry>int(time.time())+2592000:
            return None
        return uid
    except (ValueError, UnicodeDecodeError, TypeError):
        return None

def _safe_next_path(value):
    value=str(value or "/")
    return value if value.startswith("/") and not value.startswith("//") and "\r" not in value and "\n" not in value else "/"

def _login_html(next_path="/", error="", status=200):
    target=html.escape(_safe_next_path(next_path),quote=True)
    message=f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
    body='''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="theme-color" content="#0755e8"><meta name="apple-mobile-web-app-capable" content="yes"><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/app-icon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/apple-touch-icon.png"><title>Вход · Медицинский архив</title><style>:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f2f6ff;color:#172b4d}*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;padding:20px}.card{width:min(100%,420px);padding:28px;border:1px solid #dce7f8;border-radius:24px;background:#fff;box-shadow:0 18px 60px #153b7814}.brand{display:flex;align-items:center;gap:12px;margin-bottom:24px;font-weight:750;font-size:1.1rem}.brand img{width:52px;height:52px;border-radius:14px;background:#0755e8}h1{font-size:1.65rem;letter-spacing:-.04em;margin:0 0 8px}p{color:#60718d;line-height:1.5}label{display:block;font-weight:650;margin:16px 0 6px}input{width:100%;padding:13px 14px;border:1px solid #d5e0f0;border-radius:12px;font:inherit;min-height:48px}button{width:100%;margin-top:22px;padding:13px;border:0;border-radius:12px;background:#0755e8;color:#fff;font:inherit;font-weight:700;min-height:48px}.error{padding:12px;border-radius:10px;background:#fff0f0;color:#a32424}</style></head><body><main class="card"><div class="brand"><img src="/app-icon.svg" alt=""><span>Medical Assistant</span></div><h1>Войти в архив</h1><p>Войдите, чтобы открыть семейный медицинский архив.</p>'''+message+'''<form method="post" action="/auth/login"><input type="hidden" name="next" value="'''+target+'''"><label for="username">Логин</label><input id="username" name="username" autocomplete="username" required autofocus><label for="password">Пароль</label><input id="password" name="password" type="password" autocomplete="current-password" required><button type="submit">Войти</button></form></main></body></html>'''
    return HTMLResponse(body,status_code=status,headers={"Cache-Control":"no-store"})
WEB_USERNAME=os.getenv("WEB_USERNAME","").strip()
WEB_PASSWORD=os.getenv("WEB_PASSWORD","")
# Temporary shared demo credentials are retained for the private MVP testing phase.
# Before public launch, set unique DEMO_USERNAME and DEMO_PASSWORD values in .env.
DEMO_USERNAME=os.getenv("DEMO_USERNAME", "test").strip()
DEMO_PASSWORD=os.getenv("DEMO_PASSWORD", "test")
# Real web users occupy the negative 48-bit hash range; demo tenant identities
# are derived from a random, HttpOnly per-browser cookie in a separate range.
DEMO_UID_FLOOR=10**15
DEMO_UID=-(DEMO_UID_FLOOR + int(hashlib.sha256(b"medical-archive-demo-tenant-v1").hexdigest()[:14],16))
AUTH_FAILURES={}
AUTH_FAILURES_LOCK=threading.Lock()
DEMO_CLEANUP_STARTED=False
DEMO_MAX_ACTIVE_TENANTS=max(1,int(os.getenv("DEMO_MAX_ACTIVE_TENANTS","20")))
DEMO_MAX_DOCUMENTS=max(1,int(os.getenv("DEMO_MAX_DOCUMENTS","10")))
DEMO_MAX_PATIENTS=max(1,int(os.getenv("DEMO_MAX_PATIENTS","10")))
DEMO_MAX_UPLOAD_MB=min(5,max(1,int(os.getenv("DEMO_MAX_UPLOAD_MB","5"))))
ROOT=os.getenv("YANDEX_ROOT_FOLDER","MedArchive").strip("/")
STORAGE_BACKEND=os.getenv("DOCUMENT_STORAGE_BACKEND","local").strip().lower()
MAX_UPLOAD_MB=max(1,int(os.getenv("MAX_UPLOAD_MB","20")))
ALLOWED={".pdf",".png",".jpg",".jpeg",".webp",".tif",".tiff",".bmp"}
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(message)s")

def is_demo_user(uid):
    return int(uid) <= -DEMO_UID_FLOOR

@app.middleware("http")
async def demo_session_cookie(request: Request, call_next):
    """Give each HTTPS browser its own expiring demo tenant, despite shared Basic Auth."""
    is_demo_auth = False
    authorization = request.headers.get("authorization", "")
    if authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
            is_demo_auth = bool(
                DEMO_USERNAME and DEMO_PASSWORD
                and hmac.compare_digest(username.encode(), DEMO_USERNAME.encode())
                and hmac.compare_digest(password.encode(), DEMO_PASSWORD.encode())
            )
        except (ValueError, UnicodeDecodeError):
            is_demo_auth = False
    if not is_demo_auth:
        return await call_next(request)
    if request.url.path == "/upload" or request.url.path.endswith("/upload"):
        length = request.headers.get("content-length", "")
        if length.isdigit() and int(length) > (DEMO_MAX_UPLOAD_MB * 5 + 1) * 1024 * 1024:
            return Response("Демо-загрузка превышает общий лимит размера запроса.", status_code=413)
    cookie = request.cookies.get("medical_demo_session", "") or secrets.token_urlsafe(32)
    request.state.medical_demo_session = cookie
    response = await call_next(request)
    response.set_cookie("medical_demo_session", cookie, max_age=7200, httponly=True,
                        secure=True, samesite="lax", path="/")
    return response

def current_user(request: Request, credentials: HTTPBasicCredentials|None=Depends(security))->int:
    # A valid signed session takes precedence for PWA requests; legacy HTTP Basic remains supported.
    if request and request.url.path!="/auth/login":
        session_uid=_read_session(request.cookies.get(SESSION_COOKIE_NAME,""))
        if session_uid is not None:
            if is_demo_user(session_uid): _ensure_demo_tenant(session_uid)
            return session_uid
    if credentials is None:
        raise HTTPException(401,"Not authenticated")
    ip = request.client.host if request and request.client else "unknown"
    now = time.monotonic()
    rate_key = ip + ":" + hashlib.sha256(credentials.username.encode()).hexdigest()[:16]
    demo_ok = bool(DEMO_USERNAME and DEMO_PASSWORD and
                   hmac.compare_digest(credentials.username.encode(), DEMO_USERNAME.encode()) and
                   hmac.compare_digest(credentials.password.encode(), DEMO_PASSWORD.encode()))
    main_ok = bool(WEB_USERNAME and WEB_PASSWORD and
                   hmac.compare_digest(credentials.username.encode(), WEB_USERNAME.encode()) and
                   hmac.compare_digest(credentials.password.encode(), WEB_PASSWORD.encode()))
    with AUTH_FAILURES_LOCK:
        if len(AUTH_FAILURES) > 10000:
            for key, stamps in list(AUTH_FAILURES.items()):
                fresh = [stamp for stamp in stamps if now - stamp < 300]
                if fresh:
                    AUTH_FAILURES[key] = fresh
                else:
                    AUTH_FAILURES.pop(key, None)
        failures = [t for t in AUTH_FAILURES.get(rate_key, []) if now - t < 300]
        AUTH_FAILURES[rate_key] = failures
        if len(failures) >= 20 and not (demo_ok or main_ok):
            raise HTTPException(429, "Слишком много неудачных попыток входа. Попробуйте через 5 минут.")
        if demo_ok or main_ok:
            AUTH_FAILURES.pop(rate_key, None)
    if main_ok:
        return -(int(hashlib.sha256(WEB_USERNAME.encode()).hexdigest()[:12],16) or 1)
    if demo_ok:
        cookie = (getattr(request.state, "medical_demo_session", "") or request.cookies.get("medical_demo_session", "")) if request else ""
        demo_uid = -(DEMO_UID_FLOOR + int(hashlib.sha256(cookie.encode()).hexdigest()[:14], 16)) if cookie else DEMO_UID
        _ensure_demo_tenant(demo_uid)
        return demo_uid
    with AUTH_FAILURES_LOCK:
        AUTH_FAILURES.setdefault(ip, []).append(now)
    raise HTTPException(401,"Invalid username or password",headers={"WWW-Authenticate":'Basic realm="Medical Archive"'})

@app.get("/login",response_class=HTMLResponse,include_in_schema=False)
def login_page(request:Request,next_path:str="/"):
    if _read_session(request.cookies.get(SESSION_COOKIE_NAME,"")) is not None:
        return RedirectResponse(_safe_next_path(next_path),status_code=303)
    return _login_html(next_path)

@app.post("/auth/login",include_in_schema=False)
def create_login_session(request:Request,username:str=Form(...),password:str=Form(...),next_path:str=Form("/",alias="next")):
    if not _session_signing_key():
        return _login_html(next_path,"Сессии не настроены. Администратору необходимо задать WEB_SESSION_SECRET длиной не менее 32 символов.",503)
    credentials=HTTPBasicCredentials(username=username,password=password)
    demo_ok=bool(DEMO_USERNAME and DEMO_PASSWORD and hmac.compare_digest(username.encode(),DEMO_USERNAME.encode()) and hmac.compare_digest(password.encode(),DEMO_PASSWORD.encode()))
    demo_cookie=request.cookies.get("medical_demo_session","")
    if demo_ok:
        demo_cookie=demo_cookie or secrets.token_urlsafe(32)
        request.state.medical_demo_session=demo_cookie
    try:
        uid=current_user(request,credentials)
    except HTTPException:
        return _login_html(next_path,"Неверный логин или пароль.",401)
    try:
        token=_make_session(uid)
    except RuntimeError:
        return _login_html(next_path,"Не удалось создать защищённую сессию.",503)
    response=RedirectResponse(_safe_next_path(next_path),status_code=303)
    response.set_cookie(SESSION_COOKIE_NAME,token,max_age=SESSION_MAX_AGE,httponly=True,secure=True,samesite="lax",path="/")
    if demo_ok:
        response.set_cookie("medical_demo_session",demo_cookie,max_age=SESSION_MAX_AGE,httponly=True,secure=True,samesite="lax",path="/")
    response.headers["Cache-Control"]="no-store"
    return response

@app.get("/auth/status",include_in_schema=False)
def auth_status(uid:int=Depends(current_user)):
    return Response('{"authenticated":true}',media_type="application/json",headers={"Cache-Control":"no-store"})

@app.post("/auth/logout",include_in_schema=False)
def logout():
    response=RedirectResponse("/login",status_code=303)
    response.delete_cookie(SESSION_COOKIE_NAME,path="/",secure=True,httponly=True,samesite="lax")
    response.delete_cookie("medical_demo_session",path="/",secure=True,httponly=True,samesite="lax")
    response.headers["Cache-Control"]="no-store"
    return response

def _cleanup_expired_demo_tenants_once():
    """Purge artifacts only for expired tenants explicitly marked as demo."""
    import shutil
    from local_storage import DATA_ROOT
    root = DATA_ROOT.resolve()
    removed = 0
    for fid in tenancy.expired_demo_families():
        try:
            candidate = root / f"family_{int(fid)}"
            # Unlink a family-directory symlink itself; never follow it outside root.
            if candidate.is_symlink():
                candidate.unlink(missing_ok=True)
            elif candidate.exists():
                resolved = candidate.resolve(strict=True)
                if resolved.parent != root or resolved.name != candidate.name:
                    raise RuntimeError("Demo directory path is outside local storage root")
                # Do not swallow filesystem errors: leave DB metadata marked so cleanup retries.
                shutil.rmtree(candidate)
            if tenancy.delete_demo_family(fid):
                removed += 1
        except Exception:
            logging.exception("Unable to fully clean expired demo tenant %s; will retry", int(fid))
    return removed

def _ensure_demo_tenant(user_id):
    """Create a new tenant only after an expired tenant's files were successfully purged."""
    try:
        return tenancy.ensure_demo_family(user_id, max_active=DEMO_MAX_ACTIVE_TENANTS)
    except RuntimeError as first_error:
        try:
            _cleanup_expired_demo_tenants_once()
        except Exception as exc:
            logging.exception("Expired demo tenant cleanup failed")
            raise HTTPException(503, "Срок хранения демо-архива истёк, но очистка пока не завершена") from exc
        try:
            return tenancy.ensure_demo_family(user_id, max_active=DEMO_MAX_ACTIVE_TENANTS)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc or first_error)) from exc

def _cleanup_expired_demo_data():
    """Keep cleaning expired demo uploads while the web app is running."""
    while True:
        try:
            _cleanup_expired_demo_tenants_once()
        except Exception:
            logging.exception("Demo cleanup failed")
        time.sleep(60)

@app.on_event("startup")
def start_demo_cleanup_worker():
    global DEMO_CLEANUP_STARTED
    if not DEMO_CLEANUP_STARTED:
        threading.Thread(target=_cleanup_expired_demo_data, daemon=True, name="demo-data-cleanup").start()
        DEMO_CLEANUP_STARTED = True

def page(title,body,status=200):
    return HTMLResponse("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><meta name="theme-color" content="#16794b"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="apple-mobile-web-app-title" content="Медархив"><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/app-icon.svg" type="image/svg+xml"><title>"""+html.escape(title)+""" · Медицинский архив</title><style>
:root{color-scheme:light;--bg:#f4f8ff;--fg:#172b4d;--card:#ffffff;--line:#e2eaf5;--muted:#6b7b94;--field:#f8fbff;--accent:#3478df;--accent-strong:#245fc0;--accent-soft:#e6f0ff;--warn:#a76800;--danger:#b42318;--shadow:0 5px 22px rgba(35,76,130,.065);--radius:18px}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{max-width:none;margin:0;padding:22px clamp(16px,3vw,42px) 48px;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--fg);letter-spacing:-.012em}
body>h1{font-size:clamp(1.65rem,4vw,2.2rem);line-height:1.16;letter-spacing:-.045em;margin:18px 0 22px;font-weight:780}
h2{font-size:1.2rem;line-height:1.3;letter-spacing:-.025em;margin:0 0 12px}
h3{font-size:1.05rem;line-height:1.35;margin:0 0 8px}
p{margin:9px 0 13px}
small{line-height:1.45}
.card{border:1px solid var(--line);border-radius:var(--radius);padding:20px;margin:14px 0;background:var(--card);box-shadow:var(--shadow)}
input,select,button{font:inherit;max-width:100%;padding:11px 14px;margin:4px 0;border:1px solid var(--line);border-radius:11px;background:var(--field);color:var(--fg);min-height:44px}
input:focus,select:focus,button:focus-visible,a:focus-visible{outline:3px solid rgba(52,120,223,.22);outline-offset:2px}
button{cursor:pointer;font-weight:650;transition:transform .15s ease,border-color .15s ease,background .15s ease}
button:hover{border-color:var(--accent)}
button:active{transform:scale(.985)}
input[type=text],input[type=search],input[type=date],input[type=file],select{width:100%}
input[type=checkbox],input[type=radio]{width:18px;min-height:18px;accent-color:var(--accent)}
label{font-weight:650}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.muted{color:var(--muted)}
.warn,.notice-warning{border-left:4px solid var(--warn);padding:12px 15px;background:var(--card);border-radius:0 11px 11px 0;margin:12px 0}
a{overflow-wrap:anywhere;color:inherit;text-underline-offset:3px}
a:hover{color:var(--accent)}
.home-search{padding:16px 18px;margin:0 0 18px}
.home-search label{display:block;margin-bottom:5px;font-size:.94rem}
.home-search .search-row{display:flex;gap:9px;align-items:center}
.home-search input[type=search]{flex:1;min-width:0;width:auto;margin:0;background:var(--field)}
.home-search button{flex:0 0 auto;margin:0;background:var(--accent);color:#fff;border-color:var(--accent);padding-inline:17px}
.home-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0 0 20px}
.home-action{display:flex;aspect-ratio:1.2/1;align-items:center;justify-content:center;min-height:125px;padding:15px;border-radius:20px;border:1px solid var(--line);background:var(--card);text-align:center;text-decoration:none;font-weight:700;font-size:clamp(.96rem,2.8vw,1.12rem);line-height:1.35;box-shadow:var(--shadow);transition:transform .18s ease,border-color .18s ease}
.home-action:hover{transform:translateY(-2px);border-color:var(--accent);color:var(--fg)}
.home-action.primary{background:var(--accent);color:#fff;border-color:var(--accent)}
.home-action.primary:hover{background:var(--accent-strong);color:#fff}
#quick-upload{padding:14px 16px}
#quick-upload>h2{font-size:1rem;margin:0}
#quick-upload>p,#quick-upload>small{display:none}
#choose-files{display:none}
#upload-queue:empty{display:none}
.pending-thumbs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}
.pending-thumb{display:block;min-width:0;text-decoration:none}
.pending-thumb img,.file-thumb{display:flex;width:100%;height:100px;object-fit:cover;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:11px;background:var(--field)}
.pending-thumb span:last-child{display:block;font-size:.82rem;overflow-wrap:anywhere;max-height:2.6em;overflow:hidden;margin-top:5px}
.preview-image{display:block;width:100%;max-height:60vh;object-fit:contain;border:1px solid var(--line);border-radius:13px;margin:14px 0;background:var(--field)}
.upload-item{border:1px solid var(--line);border-radius:13px;padding:13px;margin:10px 0;background:var(--field)}
.upload-top{display:flex;gap:10px;align-items:center}
.upload-name{flex:1;min-width:0;overflow-wrap:anywhere}
.upload-remove{font-size:22px;line-height:1;min-width:42px;padding:5px}
.upload-track{height:7px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:9px}
.upload-fill{height:100%;width:0;background:var(--accent);transition:width .12s}
.upload-status{font-size:.9rem;color:var(--muted)}
.patient-heading{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.button-link{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:10px;padding:9px 13px;min-height:42px;text-decoration:none;font-weight:620;background:var(--card)}
.button-link:hover{border-color:var(--accent);color:var(--accent)}
.tabs{display:flex;gap:5px;border-bottom:1px solid var(--line);margin:20px 0 16px;overflow-x:auto}
.tab{flex:0 0 auto;padding:11px 14px;text-decoration:none;border-bottom:3px solid transparent;color:var(--muted);font-weight:620;white-space:nowrap}
.tab.active{border-color:var(--accent);color:var(--fg);font-weight:750}
.patient-search label{display:block;font-weight:700;margin-bottom:6px}
.timeline-date{margin:24px 0 9px;font-size:1.2rem;letter-spacing:-.025em}
.document-row{display:flex;gap:14px;align-items:center;justify-content:space-between;padding:15px;border:1px solid var(--line);border-radius:13px;margin:9px 0;background:var(--card);transition:border-color .15s ease}
.document-row:hover{border-color:rgba(52,120,223,.45)}
.document-main{min-width:0;overflow-wrap:anywhere}
.tree-group{border:1px solid var(--line);border-radius:13px;padding:15px;margin:11px 0;background:var(--card)}
.tree-group summary{cursor:pointer;font-weight:700;padding:3px 0}
.tree-group summary::marker{color:var(--accent)}
.notice-success{border-left:4px solid var(--accent);padding:12px 15px;background:var(--accent-soft);border-radius:0 11px 11px 0}
.danger{border-color:var(--danger);color:var(--danger)}
button[type=submit]{background:var(--accent);border-color:var(--accent);color:#fff}
button[type=submit]:hover{background:var(--accent-strong)}
#archive-search{flex:1 1 220px;width:auto}
hr{border:0;border-top:1px solid var(--line);margin:18px 0}
@media(max-width:600px){body{padding:17px 14px 34px}.home-actions{gap:10px}.home-action{aspect-ratio:1.05/1;min-height:120px;padding:11px;border-radius:17px;font-size:.96rem}.card{padding:16px;margin:12px 0;border-radius:15px}.home-search{padding:13px;margin-bottom:14px}.home-search .search-row{gap:7px}.home-search button{padding-inline:12px;font-size:.93rem}.document-row{align-items:flex-start;flex-direction:column}.tabs{gap:0}.tab{padding:10px 9px;font-size:.92rem}.timeline-date{margin-top:21px}.pending-thumbs{gap:8px}}

.app-shell{min-height:100vh}.app-sidebar{position:fixed;z-index:30;inset:0 auto 0 0;width:258px;padding:20px 14px;background:#fff;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:22px;transform:translateX(-102%);transition:transform .22s ease;box-shadow:0 10px 36px rgba(35,76,130,.08)}.app-sidebar.open{transform:translateX(0)}.sidebar-brand{display:flex;gap:10px;align-items:center;padding:4px 8px 16px;font-weight:800;font-size:1.05rem}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:#e2eeff;color:#2868c7;font-size:22px}.sidebar-nav{display:grid;gap:5px}.sidebar-nav a{display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:11px;text-decoration:none;color:#526681;font-weight:650}.sidebar-nav a:hover,.sidebar-nav a.active{background:#eaf2ff;color:#245fc0}.sidebar-footer{margin-top:auto;border-top:1px solid var(--line);padding:14px 8px;color:var(--muted);font-size:.85rem}.sidebar-backdrop{display:none;position:fixed;inset:0;background:rgba(20,40,70,.25);z-index:29}.sidebar-backdrop.show{display:block}.app-topbar{display:flex;align-items:center;gap:12px;margin:0 0 22px}.menu-toggle{display:grid;place-items:center;flex:0 0 44px;width:44px;height:44px;padding:0;margin:0;background:#fff;border:1px solid var(--line);color:#2868c7;font-size:22px}.app-topbar-title{font-weight:750;font-size:1rem}.home-welcome{margin:8px 0 22px}.home-welcome h1{margin:0 0 6px}.home-welcome p{color:var(--muted);margin:0}.upload-dropzone{padding:28px 18px!important;text-align:center;background:#eef5ff!important;border:1.5px dashed #a9c9fa!important;box-shadow:none!important}.upload-dropzone h2{margin:8px 0}.patient-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.patient-card{display:flex;align-items:center;gap:12px;padding:14px;border:1px solid var(--line);border-radius:15px;background:#fff;text-decoration:none;box-shadow:var(--shadow)}.patient-avatar{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border-radius:50%;background:#e2eeff;color:#2868c7;font-weight:800}.patient-card:nth-child(4n+2) .patient-avatar{background:#dcf5e9;color:#18845d}.patient-card:nth-child(4n+3) .patient-avatar{background:#eee6ff;color:#7450bd}.patient-card:nth-child(4n+4) .patient-avatar{background:#ffecd9;color:#b66b16}.patient-card:hover{border-color:#9fc3fb;transform:translateY(-1px)}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}</style></head><body><div class="app-shell"><aside class="app-sidebar" id="app-sidebar" aria-label="Основная навигация"><div class="sidebar-brand"><span class="brand-mark">✚</span><span>Medical Assistant</span></div><nav class="sidebar-nav"><a href="/" class="active">⌂　Главная</a><a href="/#quick-upload">⇧　Загрузка</a><a href="/search">⌕　Поиск</a><a href="/#patients">♧　Пациенты</a><a href="/#inbox">▤　Входящие</a><a href="/#family-settings">⚙　Настройки</a></nav><div class="sidebar-footer">Семейный медицинский архив</div></aside><div class="sidebar-backdrop" id="sidebar-backdrop"></div><main class="app-content"><header class="app-topbar"><button type="button" class="menu-toggle" id="menu-toggle" aria-label="Открыть меню" aria-expanded="false">☰</button><span class="app-topbar-title">Медицинский архив</span></header><script>(function(){const s=document.getElementById("app-sidebar"),b=document.getElementById("sidebar-backdrop"),t=document.getElementById("menu-toggle");function close(){s.classList.remove("open");b.classList.remove("show");t.setAttribute("aria-expanded","false")}t.addEventListener("click",function(){const open=!s.classList.contains("open");s.classList.toggle("open",open);b.classList.toggle("show",open);t.setAttribute("aria-expanded",String(open))});b.addEventListener("click",close);document.addEventListener("keydown",e=>{if(e.key==="Escape")close()});s.querySelectorAll("a").forEach(a=>a.addEventListener("click",close))})();</script><script>if("serviceWorker" in navigator && location.protocol==="https:"){window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}))}</script>"""+body+"""<p class="muted"><small>Тестовый MVP. Не заменяет врача.</small></p></main></div></body></html>""",status_code=status)

def display_document_title(document, analysis):
    saved=(analysis or {}).get("display_title")
    if saved: return str(saved)
    text=str(document.get("text") or "")
    import re
    if re.search(r"ультразвуков\w*\s+исследован\w*.{0,100}почек\s+и\s+мочевого\s+пузыря",text,re.I|re.S):
        return "УЗИ почек и мочевого пузыря"
    if re.search(r"ультразвуков\w*\s+исследован\w*.{0,100}щитовидной\s+железы",text,re.I|re.S):
        return "УЗИ щитовидной железы"
    kind=str(document.get("kind") or "не определено")
    if kind!="не определено": return kind[:1].upper()+kind[1:]
    return "Документ — требуется классификация"

def family(fid,uid):
    if is_demo_user(uid) and not tenancy.is_demo_family(fid):
        raise HTTPException(403,"Демо-аккаунт может работать только со своим временным архивом")
    if not tenancy.role_for_user(fid,uid): raise HTTPException(403,"Нет доступа к этому семейному архиву")
    f=tenancy.get_family(fid)
    if not f: raise HTTPException(404,"Архив не найден")
    return f

def enforce_demo_document_quota(fid, incoming=1):
    current=db.family_document_count(fid)
    if current + int(incoming) > DEMO_MAX_DOCUMENTS:
        raise HTTPException(413, f"В демо можно загрузить не более {DEMO_MAX_DOCUMENTS} документов за время сессии")

def home_url(fid=None): return RedirectResponse("/" if fid is None else f"/?family_id={int(fid)}",status_code=303)

def explicit_document_date(text):
    """Return a date only when OCR explicitly labels it as a document/exam date."""
    import re
    from datetime import datetime
    match=re.search(r"(?:дата\s+(?:документа|исследования|осмотра|выдачи|проведения|при[её]ма)|исследование\s+от|осмотр\s+от)\s*[:№]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{4})",text or "",re.I)
    if not match: return ""
    for fmt in ("%d-%m-%Y","%d.%m.%Y","%d/%m/%Y"):
        try: return datetime.strptime(match.group(1),fmt).strftime("%d-%m-%Y")
        except ValueError: pass
    return ""

@app.get("/",response_class=HTMLResponse)
def home(request:Request,family_id:int|None=None,uid:int=Depends(current_user)):
    # Browser entry serves the React shell; same-origin SPA requests ask for legacy HTML fragments.
    if request.headers.get("x-requested-with") != "MedicalArchiveSPA":
        index=Path(__file__).resolve().parent / "frontend" / "dist" / "index.html"
        if index.is_file(): return FileResponse(index,media_type="text/html",headers={"Cache-Control":"no-cache"})
    fs=tenancy.families_for_user(uid)
    if is_demo_user(uid) and not fs:
        _ensure_demo_tenant(uid)
        fs=tenancy.families_for_user(uid)
    if family_id is not None and not tenancy.role_for_user(family_id,uid): raise HTTPException(403,"Нет доступа")
    f=tenancy.get_family(family_id) if family_id is not None else (tenancy.get_family(fs[0]["id"]) if fs else None)
    b=[]
    upload_ui_limit_mb=min(MAX_UPLOAD_MB, DEMO_MAX_UPLOAD_MB) if is_demo_user(uid) else MAX_UPLOAD_MB
    if is_demo_user(uid):
        b.append('<div class="notice-warning"><strong>Демо-режим.</strong> Используйте только тестовые документы. Все данные демо-архива автоматически удаляются примерно через 2 часа после последней загрузки. ИИ-классификация отправляет OCR-текст внешнему провайдеру только после отдельного согласия.</div>')
    if fs:
        selected_for_actions = f["id"] if f else fs[0]["id"]
        pending_for_actions = len(db.pending_documents(selected_for_actions))
        patient_count = len(db.patients(selected_for_actions))
        b.append('<nav class="home-actions" aria-label="Основные действия"><a class="home-action" href="/families/' + str(selected_for_actions) + '/inbox">▤ Входящие · на проверку (' + str(pending_for_actions) + ')</a><a class="home-action" href="#patients">♧ Пациенты (' + str(patient_count) + ')</a></nav>')
        b.append('<section class="home-welcome"><h1>Добро пожаловать!</h1><p>Ваш семейный медицинский архив</p></section>')
        b.append('<form class="card row home-search" method="get" action="/search"><input type="hidden" name="family_id" value="' + str(selected_for_actions) + '"><label for="archive-search">⌕</label><input id="archive-search" type="search" name="q" placeholder="Найти документ, анализ, обследование…" required><button type="submit">Найти</button></form>')
    # Inbox-first workflow: files can be uploaded before opening a patient record.
    if fs:
        selected_fid = f["id"] if f else fs[0]["id"]
        upload_options = "".join(
            '<option value="' + str(x["id"]) + '"' + (' selected' if x["id"] == selected_fid else '') + '>' + html.escape(x["name"]) + '</option>'
            for x in fs
        )
        b.append(
            '<div class="card upload-dropzone" id="quick-upload"><div style="font-size:42px;color:#3478df">⇧</div><h2>Добавить документы</h2><p class="muted">PDF, фотографии и сканы. Можно выбрать несколько файлов сразу.</p>'
            '<p class="muted">Статус обновляется после передачи файла и завершения распознавания и классификации.</p><label style="display:block;font-weight:400"><input id="ai-classification-consent" type="checkbox" style="width:auto;min-height:auto"> Разрешаю отправить OCR-текст внешнему ИИ для уточнения типа документа</label>'
            '<select id="upload-family" hidden aria-hidden="true">' + upload_options + '</select>'
            '<input id="upload-files" type="file" accept="image/*,application/pdf,.tif,.tiff,.bmp" multiple hidden>' '<button type="button" id="choose-files">＋ Выбрать документы</button>'
            '<div id="upload-queue" aria-live="polite"></div>'
            '<small>До ' + str(upload_ui_limit_mb) + ' МБ на файл. OCR и классификация выполняются на сервере после передачи.</small></div>'
            '<script>(function(){const input=document.getElementById("upload-files"),queue=document.getElementById("upload-queue"),family=document.getElementById("upload-family");let items=[],seq=0;document.getElementById("home-upload-trigger").addEventListener("click",function(){input.click()});'
            'function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]})}'
            'function render(){queue.innerHTML=items.map(function(x){return \'<div class="upload-item"><div class="upload-top"><div class="upload-name"><strong>\'+esc(x.file.name)+\'</strong><div class="upload-status">\'+(x.file.size/1048576).toFixed(2)+\' МБ · \'+esc(x.status)+\'</div></div><button class="upload-remove" type="button" data-remove="\'+x.id+\'" aria-label="Убрать файл из списка">×</button></div><div class="upload-track"><div class="upload-fill" style="width:\'+x.progress+\'%"></div></div><small>\'+x.progress+\'%</small></div>\'}).join("");queue.querySelectorAll("[data-remove]").forEach(function(b){b.addEventListener("click",function(){const id=Number(b.dataset.remove),item=items.find(function(x){return x.id===id});if(item&&item.xhr){item.cancelled=true;item.status="Отменено в браузере; результат сервера неизвестен";item.xhr.abort()}items=items.filter(function(x){return x.id!==id});render()})})}window.addEventListener("beforeunload",function(e){if(items.some(function(x){return x.xhr&&!x.cancelled})){e.preventDefault();e.returnValue=""}});'
            'function upload(item){item.status="Загрузка";const xhr=new XMLHttpRequest(),form=new FormData();item.xhr=xhr;form.append("family_id",family.value);form.append("files",item.file,item.file.name);form.append("ai_consent",document.getElementById("ai-classification-consent")?.checked?"true":"false");xhr.open("POST","/upload");xhr.upload.onprogress=function(e){if(e.lengthComputable){item.progress=Math.round(e.loaded/e.total*100);item.status=item.progress>=100?"Передан · обработка на сервере":"Загрузка";render()}};xhr.onload=function(){item.xhr=null;if(item.cancelled)return;item.progress=100;const body=(xhr.responseText||"").toLowerCase();if(xhr.status>=200&&xhr.status<300){if(body.includes("добавлен во входящие"))item.status="100% · OCR завершён · нужна ручная проверка";else if(body.includes("документ сохранён")||body.includes("файл уже есть в индексе"))item.status="100% · OCR и классификация завершены";else if(body.includes("дубликат")||body.includes("уже сохранён в архиве"))item.status="100% · дубликат";else {item.progress=95;item.status="Передан серверу · результат обработки не подтверждён"}}else {item.progress=Math.min(item.progress,95);item.status="Ошибка HTTP "+xhr.status}render()};xhr.onerror=function(){item.xhr=null;if(!item.cancelled){item.status="Ошибка сети";render()}};xhr.onabort=function(){item.xhr=null};xhr.send(form)}'
            'document.getElementById("choose-files").addEventListener("click",function(){input.click()});input.addEventListener("change",function(){const selected=Array.from(input.files||[]);input.value="";selected.forEach(function(file){const item={id:++seq,file:file,status:"В очереди",progress:0,xhr:null,cancelled:false};if(!/\\.(pdf|png|jpe?g|webp|tiff?|bmp)$/i.test(file.name)){item.status="Формат не поддерживается";item.progress=0;items.push(item);render();return}if(file.size>'+str(upload_ui_limit_mb*1024*1024)+'){item.status="Превышен лимит размера";items.push(item);render();return}items.push(item);render();upload(item)})});'
            '})();</script>'
        )
    if f:
        fid=f["id"]
        b.append(f'<div class="card" id="patients-section"><h2>Архив: {html.escape(f["name"])}</h2><p>Хранение документов: {"локально во временном демо-хранилище" if is_demo_user(uid) else ("локально на VPS" if STORAGE_BACKEND == "local" else "Яндекс Диск")}</p>')
        if STORAGE_BACKEND == "yandex" and not is_demo_user(uid) and not tenancy.disk_connected(fid):
            b.append(f'<p><a href="/families/{fid}/connect-disk">Подключить Яндекс Диск</a></p>')
        b.append(f'<div class="patient-heading"><h2 id="patients">Пациенты</h2><a class="button-link" href="/families/{fid}/patients/new">＋ Добавить пациента</a></div><div class="patient-grid">')
        ps=db.patients(fid)
        if not ps: b.append('<p>Пациентов пока нет.</p>')
        for p in ps:
            ep=html.escape(p,quote=True)
            parts=p.split()
            short_patient=(parts[1] if len(parts)>=2 else (parts[0] if parts else p))
            b.append(f'<a class="patient-card" href="/families/{fid}/patients/{ep}"><span class="patient-avatar">{html.escape((short_patient[:1] or "П").upper())}</span><span><strong>{html.escape(short_patient)}</strong><br><small class="muted">{db.document_count(fid,p)} документов</small></span></a>')
        b.append('</div>')
    b.append('<div class="card" id="family-settings"><h2>Настройки архива</h2><form method="post" action="/families"><label>Название нового семейного архива<br><input name="name" required maxlength="80"></label> <button>Создать архив</button></form></div>')
    b.append('<div class="warn"><strong>Важно:</strong> не загружайте реальные медицинские документы до настройки резервного копирования и полной проверки прав доступа.</div>')
    return page("Главная","".join(b))

@app.get("/search",response_class=HTMLResponse)
def unified_search(q:str="",family_id:int|None=None,patient:str="",uid:int=Depends(current_user)):
    fs=tenancy.families_for_user(uid)
    if not fs:
        return page("Поиск по архиву","<p>Сначала создайте семейный архив и добавьте пациентов.</p>")
    allowed={int(x["id"]) for x in fs}
    fid=int(family_id) if family_id is not None else int(fs[0]["id"])
    if fid not in allowed: raise HTTPException(403,"Нет доступа к этому семейному архиву")
    query=" ".join((q or "").split())[:300]
    records=db.patient_records(fid)
    if not query:
        return page("Поиск по архиву",f'<p><a href="/?family_id={fid}">← В архив</a></p><form class="card" method="get" action="/search"><input type="hidden" name="family_id" value="{fid}"><input type="search" name="q" placeholder="Например: Саша анализы" required><button>Найти</button></form>')
    import re
    def norm(value):
        return re.sub(r"[^0-9a-zа-яё]+"," ",str(value or "").casefold()).strip()
    cleaned=norm(query)
    chosen=next((p for p in records if p["name"]==patient),None) if patient else None
    if chosen:
        explicit_aliases=sorted((norm(a) for a in chosen.get("aliases",[]) if norm(a)),key=len,reverse=True)
        for alias_norm in explicit_aliases:
            if re.search(r"(?<![0-9a-zа-яё])"+re.escape(alias_norm)+r"(?![0-9a-zа-яё])",cleaned):
                cleaned=re.sub(r"(?<![0-9a-zа-яё])"+re.escape(alias_norm)+r"(?![0-9a-zа-яё])"," ",cleaned,count=1).strip()
                break
    matched_aliases=[]
    if not chosen:
        for record in records:
            for alias in record.get("aliases",[]):
                alias_norm=norm(alias)
                if alias_norm and re.search(r"(?<![0-9a-zа-яё])"+re.escape(alias_norm)+r"(?![0-9a-zа-яё])",cleaned):
                    matched_aliases.append((len(alias_norm),record,alias_norm))
        if matched_aliases:
            longest=max(x[0] for x in matched_aliases)
            candidate_records={x[1]["name"]:x[1] for x in matched_aliases if x[0]==longest}
            if len(candidate_records)>1:
                options="".join('<li><a href="/search?family_id='+str(fid)+'&patient='+__import__("urllib.parse",fromlist=["quote"]).quote(name,safe="")+'&q='+__import__("urllib.parse",fromlist=["quote"]).quote(query,safe="")+'">'+html.escape(name)+'</a></li>' for name in sorted(candidate_records))
                return page("Уточните пациента",f'<p><a href="/?family_id={fid}">← В архив</a></p><h2>Кого вы имели в виду?</h2><p>Запрос совпал с несколькими пациентами. Выберите пациента, поиск не будет выполнен автоматически.</p><ul>{options}</ul>')
            chosen=next(iter(candidate_records.values()))
            cleaned=re.sub(r"(?<![0-9a-zа-яё])"+re.escape(max((x[2] for x in matched_aliases if x[0]==longest),key=len))+r"(?![0-9a-zа-яё])"," ",cleaned,count=1).strip()
    if not chosen:
        return page("Выберите пациента",f'<p><a href="/?family_id={fid}">← В архив</a></p><h2>Не удалось однозначно определить пациента</h2><p>Укажите имя или псевдоним пациента в запросе либо выберите его:</p><ul>'+ "".join('<li><a href="/search?family_id='+str(fid)+'&patient='+__import__("urllib.parse",fromlist=["quote"]).quote(p["name"],safe="")+'&q='+__import__("urllib.parse",fromlist=["quote"]).quote(query,safe="")+'">'+html.escape(p["name"])+'</a></li>' for p in records)+'</ul>')
    # Recognize common document-type wording separately from free-text terms.
    type_patterns=[
      (r"\b(?:анализы|анализ|лабораторн\w*|крови|мочи)\b","lab"),
      (r"\b(?:узи|ультразвук\w*)\b","ultrasound"),
      (r"\b(?:кт|компьютерн\w* томограф\w*)\b","ct"),
      (r"\b(?:мрт|магнитно резонансн\w*)\b","mri"),
      (r"\b(?:рентген|рентгенограф\w*)\b","xray"),
      (r"\b(?:экг|электрокардиограмм\w*)\b","ecg"),
      (r"\b(?:выписка|эпикриз)\b","discharge"),
      (r"\b(?:назначения|рецепт|лекарств\w*)\b","prescription"),
      (r"\b(?:прививки|вакцинац\w*)\b","vaccine")
    ]
    type_hint=None
    for pattern,hint in type_patterns:
        if re.search(pattern,cleaned):
            type_hint=hint
            cleaned=re.sub(pattern," ",cleaned).strip()
            break
    terms=" ".join(cleaned.split())
    rows=db.search(fid,chosen["name"],terms,1000)
    if type_hint:
        def has_type(doc):
            a=doc.get("analysis") or {}
            blob=norm(" ".join([str(doc.get("kind") or ""),*map(str,a.get("types",[])),*map(str,a.get("document_types",[])),str(a.get("primary_category") or "")]))
            checks={
              "lab":("лаборатор","анализ","кров","моч"),
              "ultrasound":("узи","ультразвук"),
              "ct":("кт","компьютерн"),
              "mri":("мрт","магнитно резонанс"),
              "xray":("рентген",),
              "ecg":("экг","электрокардиограмм"),
              "discharge":("выпис","эпикриз"),
              "prescription":("рецепт","назначен","лекарств"),
              "vaccine":("вакцин","привив")
            }
            return any(term in blob for term in checks[type_hint])
        rows=[d for d in rows if has_type(d)]
    b=[f'<p><a href="/?family_id={fid}">← В архив</a></p><h2>Результаты поиска</h2><p>Пациент: <strong>{html.escape(chosen["name"])}</strong></p><p>Запрос: {html.escape(query)} · найдено документов: {len(rows)}</p>']
    if not rows:
        b.append('<div class="card">Подходящие документы не найдены. Попробуйте уточнить запрос или выбрать другой тип документа.</div>')
    for d in rows:
        a=d.get("analysis") or {}
        title=display_document_title(d,a)
        link=f'<p><a href="/families/{fid}/documents/{int(d["id"])}">Открыть оригинал</a></p>' if (STORAGE_BACKEND=="local" or is_demo_user(uid)) and d.get("remote") else ""
        b.append(f'<div class="card"><strong>{html.escape(str(title))}</strong><br>Тип: {html.escape(str(d.get("kind") or "не определено"))}<br>Дата: {html.escape(str(d.get("date") or "не указана"))}{link}<p><a href="/families/{fid}/patients/{__import__("urllib.parse",fromlist=["quote"]).quote(chosen["name"],safe="")}">История пациента</a></p><details><summary>Показать OCR-текст</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+html.escape((d.get("text") or "")[:4000])+'</pre></details></div>')
    return page("Поиск по архиву","".join(b))

@app.get("/settings",response_class=HTMLResponse)
def archive_settings(family_id:int|None=None,updated:int=0,uid:int=Depends(current_user)):
    fs=tenancy.families_for_user(uid)
    f=tenancy.get_family(family_id) if family_id is not None else (tenancy.get_family(fs[0]["id"]) if fs else None)
    if not f: return page("Настройки архива",'<h1>Настройки архива</h1><p>Сначала создайте семейный архив.</p><a class="button-link" href="/">На главную</a>')
    family(int(f["id"]),uid)
    role=tenancy.role_for_user(int(f["id"]),uid)
    body=['<h1>Настройки архива</h1><p class="muted">Настройки семейного медицинского архива.</p>']
    if is_demo_user(uid):
        body.append('<div class="notice-warning"><strong>Демо-режим.</strong> Временный архив хранится только локально и очищается автоматически примерно через 2 часа.</div>')
    if updated: body.append('<div class="notice-success" role="status">Название архива сохранено.</div>')
    body.append('<form class="card" method="post" action="/settings"><input type="hidden" name="family_id" value="'+str(int(f["id"]))+'"><h2>Название архива</h2><label>Название<input name="name" maxlength="80" required value="'+html.escape(str(f["name"]),quote=True)+'" '+('' if role=="owner" else 'disabled')+'></label>')
    if role=="owner": body.append('<button type="submit">Сохранить название</button>')
    else: body.append('<p class="muted">Переименовывать архив может только владелец.</p>')
    body.append('</form>')
    body.append('<section class="card"><h2>Хранение документов</h2><p>Текущий режим: '+('локально во временном демо-хранилище' if is_demo_user(uid) else ('Яндекс Диск' if STORAGE_BACKEND=="yandex" else 'локально на VPS'))+'</p>')
    if is_demo_user(uid):
        body.append('<p class="muted">Подключение внешнего хранилища отключено для демо-аккаунта.</p>')
    elif STORAGE_BACKEND=="yandex":
        body.append('<p>'+('Яндекс Диск подключён.' if tenancy.disk_connected(int(f["id"])) else 'Яндекс Диск ещё не подключён.')+'</p>')
        if not tenancy.disk_connected(int(f["id"])): body.append('<p><a class="button-link" href="/families/'+str(int(f["id"]))+'/connect-disk">Подключить Яндекс Диск</a></p>')
    else:
        body.append('<p class="muted">Подключение Яндекс Диска добавим отдельным этапом, сохранив локальное хранилище как текущий рабочий вариант.</p>')
    body.append('</section><section class="card"><h2>Резервное копирование</h2><p>Перед загрузкой реальных медицинских документов проверьте наличие внешней резервной копии и возможность восстановления.</p></section>')
    return page("Настройки архива","".join(body))

@app.post("/settings",response_class=HTMLResponse)
def save_archive_settings(family_id:int=Form(...),name:str=Form(...),uid:int=Depends(current_user)):
    family(family_id,uid)
    try: tenancy.rename_family(family_id,name,uid)
    except PermissionError as e: raise HTTPException(403,str(e))
    except ValueError as e: raise HTTPException(400,str(e))
    return RedirectResponse("/settings?family_id="+str(family_id)+"&updated=1",status_code=303)

@app.post("/families")
def create_family(name:str=Form(...),uid:int=Depends(current_user)):
    if is_demo_user(uid): raise HTTPException(403,"В демо-режиме доступен один временный архив")
    try: fid=tenancy.create_family(name,uid)
    except ValueError as e: raise HTTPException(400,str(e))
    return home_url(fid)

@app.post("/families/{fid}/patients")
def add_patient(fid:int,name:str=Form(...),birth_date:str=Form(""),aliases:str=Form(""),uid:int=Depends(current_user)):
    family(fid,uid)
    if is_demo_user(uid) and len(db.patients(fid)) >= DEMO_MAX_PATIENTS:
        raise HTTPException(413, f"В демо можно создать не более {DEMO_MAX_PATIENTS} карточек пациентов")
    if is_demo_user(uid): tenancy.refresh_demo_expiry(fid)
    from datetime import datetime
    birth_date=(birth_date or "").strip()
    if birth_date:
        try: birth_date=datetime.strptime(birth_date,"%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError: raise HTTPException(400,"Проверьте дату рождения")
    alias_list=[x.strip() for x in (aliases or "").replace(";",",").split(",") if x.strip()]
    db.add_patient(fid,name,aliases=alias_list,birth_date=birth_date or None)
    return home_url(fid)

@app.get("/families/{fid}/patients/new",response_class=HTMLResponse)
def new_patient_page(fid:int,uid:int=Depends(current_user)):
    family(fid,uid)
    body=('<p><a href="/?family_id='+str(fid)+'">← В архив</a></p><h2>Новый пациент</h2><form class="card" method="post" action="/families/'+str(fid)+'/patients"><label>Полное ФИО<br><input name="name" required maxlength="100" placeholder="Иванов Александр Сергеевич"></label><br><label>Дата рождения<br><input type="date" name="birth_date"></label><br><label>Другие варианты имени (через запятую)<br><input name="aliases" maxlength="500" placeholder="Саша, Александр"></label><p class="muted">Дата рождения помогает сверять документы, но не является единственным подтверждением личности.</p><button type="submit">Создать карточку</button></form>')
    return page("Новый пациент",body)


@app.get("/families/{fid}/patients/{patient}/edit",response_class=HTMLResponse)
def edit_patient_page(fid:int,patient:str,uid:int=Depends(current_user)):
    family(fid,uid)
    record=next((p for p in db.patient_records(fid) if p["name"].casefold()==patient.casefold()),None)
    if not record: raise HTTPException(404,"Член семьи не найден")
    from datetime import datetime
    date_value=""
    try: date_value=datetime.strptime(record.get("birth_date") or "", "%d-%m-%Y").strftime("%Y-%m-%d")
    except ValueError: pass
    aliases=", ".join(x for x in record.get("aliases",[]) if x.casefold()!=patient.casefold())
    from urllib.parse import quote
    base="/families/"+str(fid)+"/patients/"+quote(patient,safe="")
    body=('<p><a href="'+base+'">← К карточке</a></p><h2>Данные члена семьи</h2>'
          '<form class="card" method="post" action="'+base+'/edit">'
          '<label>Имя и фамилия<input name="name" required maxlength="100" value="'+html.escape(record["name"],quote=True)+'"></label>'
          '<label>Дата рождения<input type="date" name="birth_date" value="'+date_value+'"></label>'
          '<label>Другие варианты имени<input name="aliases" maxlength="500" value="'+html.escape(aliases,quote=True)+'" placeholder="Через запятую"></label>'
          '<p class="muted">При переименовании карточки связанные документы будут привязаны к новому имени.</p>'
          '<button type="submit">Сохранить изменения</button></form>')
    return page("Редактирование члена семьи",body)

@app.post("/families/{fid}/patients/{patient}/edit",response_class=HTMLResponse)
def save_patient_page(fid:int,patient:str,name:str=Form(...),birth_date:str=Form(""),aliases:str=Form(""),uid:int=Depends(current_user)):
    family(fid,uid)
    from datetime import datetime
    from urllib.parse import quote
    birth_date=(birth_date or "").strip()
    if birth_date:
        try: birth_date=datetime.strptime(birth_date,"%Y-%m-%d").strftime("%d-%m-%Y")
        except ValueError: raise HTTPException(400,"Проверьте дату рождения")
    alias_list=[x.strip() for x in (aliases or "").replace(";",",").split(",") if x.strip()]
    try: db.update_patient_profile(fid,patient,name,birth_date or None,alias_list)
    except ValueError as e: raise HTTPException(400,str(e))
    return RedirectResponse("/families/"+str(fid)+"/patients/"+quote(" ".join(name.split()),safe="")+"?updated=1",status_code=303)

@app.get("/families/{fid}/patients/{patient}",response_class=HTMLResponse)
def patient_page(fid:int,patient:str,q:str="",view:str="timeline",deleted:int=0,cleanup_warning:int=0,uid:int=Depends(current_user)):
    family(fid,uid)
    if patient not in db.patients(fid): raise HTTPException(404,"Пациент не найден")
    upload_ui_limit_mb=min(MAX_UPLOAD_MB, DEMO_MAX_UPLOAD_MB) if is_demo_user(uid) else MAX_UPLOAD_MB
    view = "tree" if view == "tree" else "timeline"
    rows=db.search(fid,patient,q,limit=1000)
    from urllib.parse import quote
    safe_patient=quote(patient,safe="")
    base=f"/families/{fid}/patients/{safe_patient}"
    b=[f'<p><a href="/?family_id={fid}">← К архиву</a></p>',f'<div class="patient-heading"><div><h2>{html.escape(patient)}</h2><p class="muted">Документов: {len(rows)}</p></div><div class="row"><a class="button-link" href="/families/{fid}/patients/{safe_patient}/edit">✎ Редактировать</a><a class="button-link" href="#patient-upload">＋ Добавить документы</a></div></div>']
    if deleted: b.append('<div class="notice-success" role="status">Документ удалён из архива.</div>')
    if cleanup_warning: b.append('<div class="notice-warning" role="status">Запись удалена, но временный файл не удалось окончательно очистить. Проверьте журнал приложения.</div>')
    b.append(f'<form class="card patient-search" method="get" action="{base}"><label for="patient-q">Поиск по документам пациента</label><div class="row"><input id="patient-q" type="search" name="q" value="{html.escape(q,quote=True)}" placeholder="Например: анализы, УЗИ, выписка"><input type="hidden" name="view" value="{view}"><button type="submit">Найти</button>')
    if q: b.append(f'<a class="button-link" href="{base}?view={view}">Сбросить</a>')
    b.append('</div></form>')
    if STORAGE_BACKEND == "yandex" and not is_demo_user(uid) and not tenancy.disk_connected(fid):
        b.append(f'<div class="card"><a href="/families/{fid}/connect-disk">Подключить Яндекс Диск</a></div>')
    else:
        b.append(f'<div class="card" id="patient-upload"><h3>Добавить документы</h3><form method="post" enctype="multipart/form-data" action="/families/{fid}/patients/{html.escape(patient,quote=True)}/upload"><input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" required><label style="font-weight:400"><input type="checkbox" name="ai_consent" value="true" style="width:auto;min-height:auto"> Разрешаю отправить OCR-текст внешнему ИИ для уточнения типа документа</label><button type="submit">Загрузить и распознать</button></form><small class="muted">PDF и изображения · до {upload_ui_limit_mb} МБ на файл</small></div>')
    b.append('<nav class="tabs" aria-label="Вид документов">')
    b.append(f'<a class="tab {"active" if view=="timeline" else ""}" href="{base}?view=timeline&q={quote(q)}">Хронология</a><a class="tab {"active" if view=="tree" else ""}" href="{base}?view=tree&q={quote(q)}">Дерево документов</a></nav>')
    if not rows: b.append('<div class="card"><p>Документы не найдены.</p><p class="muted">Попробуйте изменить запрос или загрузить документ.</p></div>')
    elif view == "timeline":
        grouped={}
        for d in rows: grouped.setdefault(str(d.get("date") or "Дата не указана"),[]).append(d)
        from datetime import datetime
        def sort_date(item):
            try: return datetime.strptime(item[0],"%d-%m-%Y")
            except Exception: return datetime.min
        for date,docs in sorted(grouped.items(),key=sort_date,reverse=True):
            b.append(f'<h3 class="timeline-date">{html.escape(date)}</h3>')
            for d in docs:
                title=display_document_title(d,d.get("analysis") or {}); did=int(d["id"])
                b.append(f'<article class="document-row"><div class="document-main"><strong>{html.escape(str(title))}</strong><div class="muted">{html.escape(str(d.get("kind") or "не определено"))} · {html.escape(str(d.get("name") or ""))}</div></div><a class="button-link" href="/families/{fid}/documents/{did}/edit">Открыть</a></article>')
    else:
        grouped={}
        for d in rows: grouped.setdefault(str(d.get("kind") or "Не определено"),[]).append(d)
        for kind,docs in sorted(grouped.items(),key=lambda x:x[0].casefold()):
            b.append(f'<details class="tree-group" open><summary>{html.escape(kind)} <span class="muted">({len(docs)})</span></summary>')
            for d in sorted(docs,key=lambda x:str(x.get("date") or ""),reverse=True):
                title=display_document_title(d,d.get("analysis") or {}); did=int(d["id"])
                b.append(f'<div class="document-row"><div class="document-main"><strong>{html.escape(str(title))}</strong><div class="muted">{html.escape(str(d.get("date") or "Дата не указана"))}</div></div><a class="button-link" href="/families/{fid}/documents/{did}/edit">Открыть</a></div>')
            b.append('</details>')
    return page("Пациент","".join(b))

@app.post("/families/{fid}/documents/{doc_id}/delete",response_class=HTMLResponse)
def delete_document(fid:int,doc_id:int,confirm:str=Form(...),uid:int=Depends(current_user)):
    family(fid,uid)
    if confirm != "yes":
        raise HTTPException(400,"Удаление не подтверждено")
    if STORAGE_BACKEND != "local" and not is_demo_user(uid):
        raise HTTPException(503,"На текущем этапе поддерживается только локальное хранилище")
    d=db.get_doc(fid,doc_id)
    if not d:
        raise HTTPException(404,"Документ не найден")
    patient=str(d.get("patient") or "")
    from local_storage import DATA_ROOT, _component
    import uuid
    root=DATA_ROOT.resolve()
    expected=(root / f"family_{int(fid)}" / _component(patient)).resolve()
    if root not in expected.parents:
        raise HTTPException(400,"Каталог пациента вне хранилища; удаление остановлено")
    staged=[]
    try:
        # Validate every path before moving any file. Never follow a symlink
        # or touch files outside this family's patient directory.
        candidates=[]
        seen=set()
        for raw in (d.get("remote"),d.get("ocr_remote")):
            if not raw:
                continue
            original=Path(str(raw))
            if original.is_symlink():
                raise HTTPException(400,"Обнаружена символическая ссылка; удаление остановлено")
            resolved=original.resolve(strict=False)
            if resolved.parent != expected or root not in resolved.parents:
                raise HTTPException(400,"Путь файла не совпадает с каталогом пациента; удаление остановлено")
            if resolved in seen:
                continue
            seen.add(resolved)
            if resolved.exists():
                if not resolved.is_file():
                    raise HTTPException(400,"Ожидался обычный файл; удаление остановлено")
                candidates.append(resolved)
        # Stage all files with atomic renames first. If any rename or DB
        # operation fails, restore staged files before returning an error.
        for path in candidates:
            trash=path.with_name(f".{path.name}.deleting-{uuid.uuid4().hex}")
            os.replace(path,trash)
            staged.append((path,trash))
        if not db.delete_doc(fid,doc_id):
            raise RuntimeError("database row was not deleted")
    except HTTPException:
        for original,trash in reversed(staged):
            try:
                if trash.exists() and not original.exists():
                    os.replace(trash,original)
            except OSError:
                logging.exception("Failed to restore staged document file %s", original)
        raise
    except Exception:
        logging.exception("Document deletion staging failed for doc_id=%s",doc_id)
        restore_failed=False
        for original,trash in reversed(staged):
            try:
                if trash.exists() and not original.exists():
                    os.replace(trash,original)
            except OSError:
                restore_failed=True
                logging.exception("Failed to restore staged document file %s",original)
        detail="Не удалось удалить документ; запись архива сохранена."
        if restore_failed:
            detail+=" Часть файлов требует ручной проверки."
        raise HTTPException(500,detail)
    cleanup_failed=[]
    for original,trash in staged:
        try:
            trash.unlink(missing_ok=True)
        except OSError:
            cleanup_failed.append(trash.name)
            logging.exception("Staged document file cleanup failed: %s",trash)
    status="deleted=1"
    if cleanup_failed:
        status="deleted=1&cleanup_warning=1"
    return RedirectResponse("/families/"+str(fid)+"/patients/"+__import__("urllib.parse",fromlist=["quote"]).quote(patient,safe="")+"?"+status,status_code=303)

@app.get("/families/{fid}/documents/{doc_id}/original")
def view_document_original(fid: int, doc_id: int, uid: int = Depends(current_user)):
    """Serve a private PDF inline after validating family access and its storage path."""
    family(fid, uid)
    if STORAGE_BACKEND != "local" and not is_demo_user(uid):
        raise HTTPException(503, "Встроенный просмотр пока поддерживает локальное хранилище")
    d = db.get_doc(fid, doc_id)
    if not d:
        raise HTTPException(404, "Документ не найден")
    if Path(str(d.get("name") or "")).suffix.lower() != ".pdf":
        raise HTTPException(415, "Встроенный просмотр доступен только для PDF")
    from local_storage import DATA_ROOT, _component
    root = DATA_ROOT.resolve()
    patient = str(d.get("patient") or "")
    try:
        expected = (root / f"family_{int(fid)}" / _component(patient)).resolve()
        if root not in expected.parents:
            raise HTTPException(400, "Каталог документа вне хранилища")
        raw = Path(str(d.get("remote") or ""))
        if not str(d.get("remote") or "") or raw.is_symlink():
            raise HTTPException(404, "Оригинал PDF не найден")
        resolved = raw.resolve(strict=True)
        if resolved.parent != expected or root not in resolved.parents or not resolved.is_file():
            raise HTTPException(404, "Оригинал PDF не найден")
    except (OSError, ValueError):
        raise HTTPException(404, "Оригинал PDF не найден")
    return FileResponse(
        resolved,
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/families/{fid}/documents/{doc_id}/edit", response_class=HTMLResponse)
def edit_document(fid:int,doc_id:int,uid:int=Depends(current_user)):
    family(fid,uid)
    d=db.get_doc(fid,doc_id)
    if not d: raise HTTPException(404,"Документ не найден")
    from AIAnalise import DOCUMENT_TYPE_RULES
    kinds=["не определено"]+sorted(DOCUMENT_TYPE_RULES.keys())
    options="".join("<option value=\"" + html.escape(k,quote=True) + "\"" + (" selected" if k==d.get("kind") else "") + ">" + html.escape(k) + "</option>" for k in kinds)
    analysis=d.get("analysis") or {}
    title=display_document_title(d, analysis)
    patient=html.escape(str(d.get("patient") or ""),quote=True)
    body="<p><a href=\"/families/"+str(fid)+"/patients/"+patient+"\">← Назад к документам</a></p>"
    body+="<h2>Редактирование карточки документа</h2><div class=\"card\"><strong>Пациент:</strong> "+html.escape(str(d.get("patient") or ""))+"<br><strong>Исходный файл:</strong> "+html.escape(str(d.get("name") or ""))+"</div>"
    if (STORAGE_BACKEND == "local" or is_demo_user(uid)) and Path(str(d.get("name") or "")).suffix.lower() == ".pdf":
        viewer_url = f"/families/{fid}/documents/{doc_id}/original"
        body += (
            '<section class="card"><h3>Просмотр PDF</h3>'
            '<iframe src="' + viewer_url + '#toolbar=1&navpanes=0&scrollbar=1" '
            'title="Просмотр PDF" loading="lazy" '
            'style="display:block;width:100%;height:75vh;min-height:420px;border:1px solid #d8e2f0;border-radius:12px;background:#fff"></iframe>'
            '<p><a target="_blank" rel="noopener" href="' + viewer_url + '">Открыть PDF отдельно</a></p></section>'
        )
    body+="<form method=\"post\" action=\"/families/"+str(fid)+"/documents/"+str(doc_id)+"/edit\"><label>Тип обследования<br><select name=\"kind\" required>"+options+"</select></label><br>"
    body+="<label>Название для архива<br><input type=\"text\" name=\"title\" maxlength=\"180\" value=\""+html.escape(str(title),quote=True)+"\" required></label><br>"
    body+="<label>Дата документа (ДД-ММ-ГГГГ)<br><input type=\"text\" name=\"date\" maxlength=\"10\" placeholder=\"17-03-2025\" value=\""+html.escape(str(d.get("date") or ""),quote=True)+"\"></label>"
    body+="<p class=\"muted\">Оригинал и первоначальный OCR-текст останутся без изменений.</p><button type=\"submit\">Сохранить изменения</button></form>"
    body+='<form method="post" action="/families/'+str(fid)+'/documents/'+str(doc_id)+'/delete" onsubmit="return confirm(\'Удалить документ и его OCR-файл из архива? Это действие нельзя отменить.\')"><input type="hidden" name="confirm" value="yes"><button class="danger" type="submit">Удалить документ</button></form>'
    return page("Редактирование документа",body)

@app.post("/families/{fid}/documents/{doc_id}/edit", response_class=HTMLResponse)
def save_document_edit(fid:int,doc_id:int,kind:str=Form(...),title:str=Form(...),date:str=Form(""),uid:int=Depends(current_user)):
    family(fid,uid)
    d=db.get_doc(fid,doc_id)
    if not d: raise HTTPException(404,"Документ не найден")
    from AIAnalise import DOCUMENT_TYPE_RULES, DOCUMENT_TAXONOMY
    from datetime import datetime
    if kind!="не определено" and kind not in DOCUMENT_TYPE_RULES: raise HTTPException(400,"Неизвестный тип документа")
    title=" ".join((title or "").split()).strip()[:180]
    if not title: raise HTTPException(400,"Название документа не может быть пустым")
    date=(date or "").strip()
    if date:
        try: date=datetime.strptime(date,"%d-%m-%Y").strftime("%d-%m-%Y")
        except ValueError: raise HTTPException(400,"Дата должна быть в формате ДД-ММ-ГГГГ")
    analysis=d.get("analysis") or {}
    analysis["primary_type"]=kind
    analysis["primary_category"]=DOCUMENT_TAXONOMY.get(kind,{}).get("category","не определено")
    analysis["taxonomy_path"]=[analysis["primary_category"],kind] if kind in DOCUMENT_TAXONOMY else []
    analysis["document_types"]=[kind] if kind!="не определено" else []
    analysis["types"]=[kind] if kind!="не определено" else []
    analysis["confidence"]="manual" if kind!="не определено" else "low"
    analysis["review_required"]=kind=="не определено"
    analysis["display_title"]=title
    if not db.update_doc_metadata(fid,doc_id,kind,date,analysis): raise HTTPException(404,"Документ не найден")
    return RedirectResponse("/families/"+str(fid)+"/patients/"+str(d.get("patient") or ""),status_code=303)

@app.post("/upload", response_class=HTMLResponse)
def upload_inbox(family_id:int=Form(...), files:list[UploadFile]=File(...), ai_consent:bool=Form(False), uid:int=Depends(current_user)):
    """Batch inbox upload: infer patient from OCR, never guess when matching is ambiguous."""
    f=family(family_id,uid)
    if is_demo_user(uid):
        if family_id not in {int(x["id"]) for x in tenancy.families_for_user(uid)}:
            raise HTTPException(403,"Нет доступа к демо-архиву")
        tenancy.refresh_demo_expiry(family_id)
    storage_backend = "local" if is_demo_user(uid) else STORAGE_BACKEND
    upload_limit_mb = min(MAX_UPLOAD_MB, DEMO_MAX_UPLOAD_MB) if is_demo_user(uid) else MAX_UPLOAD_MB
    if is_demo_user(uid):
        if len(files) > 5:
            raise HTTPException(413,"В демо разрешено не более 5 файлов за одну загрузку")
        enforce_demo_document_quota(family_id, len(files))
    if not files:
        raise HTTPException(400,"Выберите хотя бы один файл")
    if storage_backend not in {"local","yandex"}:
        raise HTTPException(503,"Неизвестный backend хранения")
    token=tenancy.get_yadisk_token(family_id) if storage_backend=="yandex" else None
    if storage_backend=="yandex" and not token:
        raise HTTPException(400,"Сначала подключите Яндекс Диск для выбранного архива")
    roster=db.patient_records(family_id)
    if not roster:
        return page("Нужны пациенты",
            '<p>В выбранном архиве пока нет пациентов. Добавьте короткие имена и варианты ФИО, чтобы система могла безопасно распределять документы.</p>'
            '<p><a href="/?family_id='+str(family_id)+'">Вернуться в архив</a></p>',400)
    results=[]
    for upload_file in files[:50]:
        name=Path(upload_file.filename or "document.bin").name
        ext=Path(name).suffix.lower()
        if ext not in ALLOWED:
            results.append('<li><strong>'+html.escape(name)+'</strong>: формат не поддерживается; пропущен.</li>')
            continue
        saved_paths=[]
        try:
            with tempfile.TemporaryDirectory() as td:
                local=Path(td)/name
                size=0
                with local.open("wb") as out:
                    while True:
                        chunk=upload_file.file.read(1024*1024)
                        if not chunk: break
                        size+=len(chunk)
                        if size>upload_limit_mb*1024*1024:
                            break
                        out.write(chunk)
                if size==0 or size>upload_limit_mb*1024*1024:
                    results.append('<li><strong>'+html.escape(name)+'</strong>: файл пустой или превышает '+str(upload_limit_mb)+' МБ; пропущен.</li>')
                    continue
                text=ocr_file(str(local))
                analysis=analyze_document(text)
                if ai_consent and os.getenv("AI_CLASSIFICATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
                    try:
                        analysis=classify_with_ai(text, analysis)
                    except Exception as exc:
                        logging.warning("AI classification unavailable (%s); retaining local classification", type(exc).__name__)
                patient=extract_registered_patient(text,roster)
                document_dob=extract_patient_birth_date(text)
                # A DOB can disambiguate only when it uniquely matches a registered patient.
                dob_matches=[p for p in roster if document_dob and p.get("birth_date")==document_dob]
                if len(dob_matches)==1:
                    dob_patient=dob_matches[0]["name"]
                    if patient and patient!=dob_patient:
                        patient=None  # name and DOB conflict: require human review
                    elif not patient:
                        patient=dob_patient
                elif document_dob and patient:
                    registered=next((p for p in roster if p["name"]==patient),None)
                    if registered and registered.get("birth_date") and registered["birth_date"]!=document_dob:
                        patient=None
                digest=hashlib.sha256(local.read_bytes()).hexdigest()
                if not patient:
                    pending_id=db.add_pending_doc(family_id,name,digest,local.read_bytes(),text,analysis)
                    if pending_id is None:
                        results.append('<li><strong>'+html.escape(name)+'</strong>: такой документ уже находится во входящих.</li>')
                    else:
                        results.append('<li><strong>'+html.escape(name)+'</strong>: добавлен во входящие документы для ручного назначения пациента и классификации.</li>')
                    continue
                kind=analysis["primary_type"]
                keywords=extract_keywords(text,analysis)
                date=parse_date_from_text(text)
                if db.document_exists(family_id,patient,digest):
                    results.append('<li><strong>'+html.escape(name)+'</strong>: дубликат — уже есть у пациента '+html.escape(patient)+'.</li>')
                    continue
                ex=normalize_extension(name)
                stored=f"{Path(format_filename(patient,kind,date,ex)).stem}_{digest[:8]}.{ex}"
                ocr_stored=Path(stored).stem+".txt"
                if storage_backend=="local":
                    saved_path=save_local_file(family_id,patient,stored,local); saved_paths.append(saved_path)
                    ocr_tmp=Path(td)/ocr_stored; ocr_tmp.write_text(text,encoding="utf-8")
                    saved_paths.append(save_local_file(family_id,patient,ocr_stored,ocr_tmp))
                    remote=str(saved_path); oremote=str(saved_path.parent/ocr_stored)
                else:
                    disk=YaDiskClient(token); folder=f"{ROOT}/family_{family_id}/{safe_name(patient)}"
                    docs,ocr=folder+"/docs",folder+"/OCR"
                    disk.ensure_folder(docs); disk.ensure_folder(ocr)
                    remote,oremote=docs+"/"+stored,ocr+"/"+ocr_stored
                    disk.upload_file(str(local),remote)
                    with tempfile.TemporaryDirectory() as od:
                        op=Path(od)/"ocr.txt"; op.write_text(text,encoding="utf-8"); disk.upload_file(str(op),oremote)
                if not db.add_doc(family_id,patient,stored,kind,date,remote,oremote,text,keywords,digest,analysis=analysis):
                    if storage_backend=="local":
                        for candidate in saved_paths:
                            try: candidate.unlink()
                            except FileNotFoundError: pass
                    results.append('<li><strong>'+html.escape(name)+'</strong>: дубликат, запись не добавлена.</li>')
                    continue
                if storage_backend=="yandex":
                    with tempfile.TemporaryDirectory() as hd:
                        hp=Path(hd)/"history.txt"; hp.write_text(db.history(family_id,patient),encoding="utf-8")
                        disk.upload_file(str(hp),folder+"/history.txt")
                review="; требуется проверить тип" if analysis.get("review_required") else ""
                results.append('<li><strong>'+html.escape(name)+'</strong>: сохранён пациенту <strong>'+html.escape(patient)+'</strong>; тип: '+html.escape(kind)+'; дата: '+html.escape(str(date or "не указана"))+review+'.</li>')
        except Exception as e:
            for candidate in saved_paths:
                try: candidate.unlink()
                except FileNotFoundError: pass
            logging.exception("Inbox upload failed (%s)",type(e).__name__)
            results.append('<li><strong>'+html.escape(name)+'</strong>: ошибка обработки ('+html.escape(type(e).__name__)+').</li>')
        finally:
            try: upload_file.file.close()
            except Exception: pass
    body='<p><a href="/?family_id='+str(family_id)+'">← В архив</a></p><h2>Результаты загрузки</h2><div class="card"><ul>'+''.join(results)+'</ul></div>'
    return page("Результаты загрузки",body)



@app.get("/families/{fid}/inbox", response_class=HTMLResponse)
def review_inbox(fid:int,uid:int=Depends(current_user)):
    family(fid,uid)
    rows=db.pending_documents(fid)
    body=[f'<p><a href="/?family_id={fid}">← В архив</a></p><h2>Нераспознанные документы</h2><p>Документы здесь сохранены в зашифрованном виде до назначения пациента.</p>']
    if not rows:
        body.append('<div class="card">Входящих документов нет.</div>')
    if rows:
        patient_options = "".join('<option value="' + html.escape(p,quote=True) + '">' + html.escape(p) + '</option>' for p in db.patients(fid))
        body.append('<form class="card" method="post" action="/families/' + str(fid) + '/inbox/assign-selected"><h3>Массовое назначение пациента</h3><p>Отметьте документы одного человека. Тип и дата каждого документа сохраняются отдельно, если их удалось определить.</p><label>Назначить пациенту<br><select name="patient" required>' + patient_options + '</select></label>')
        for row in rows:
            body.append(f'<div class="card"><label><input type="checkbox" name="pending_ids" value="{int(row["id"])}"> <strong>{html.escape(row["name"])}</strong></label><p>Добавлен: {html.escape(row["created"])}</p><a href="/families/{fid}/inbox/{row["id"]}">Открыть и классифицировать отдельно</a></div>')
        body.append('<button type="submit">Назначить выбранные документы</button></form>')
    return page("Нераспознанные документы","".join(body))

@app.post("/families/{fid}/inbox/assign-selected", response_class=HTMLResponse)
def assign_selected_pending(fid:int,patient:str=Form(...),pending_ids:list[int]=Form(...),uid:int=Depends(current_user)):
    family(fid,uid)
    if patient not in db.patients(fid): raise HTTPException(400,"Выбранный пациент не найден")
    ids=list(dict.fromkeys(int(x) for x in pending_ids))
    if not ids or len(ids)>50: raise HTTPException(400,"Выберите от 1 до 50 документов")
    results=[]
    from AIAnalise import DOCUMENT_TYPE_RULES
    for pending_id in ids:
        d=db.get_pending_doc(fid,pending_id)
        if not d:
            results.append("<li>Документ #"+str(pending_id)+": не найден, пропущен.</li>")
            continue
        analysis=d.get("analysis") or {}
        kind=str(analysis.get("primary_type") or "не определено")
        if kind not in DOCUMENT_TYPE_RULES: kind="не определено"
        title=str(analysis.get("display_title") or (kind if kind!="не определено" else Path(d["name"]).stem))[:180].strip()
        # Avoid confusing a patient's date of birth with the document date.
        date=explicit_document_date(d.get("text") or "")
        try:
            response=assign_pending_document(fid,pending_id,patient,kind,title,date,uid)
            results.append("<li><strong>"+html.escape(d["name"])+"</strong>: назначен пациенту "+html.escape(patient)+"; индивидуальные тип и дата сохранены.</li>")
        except HTTPException as exc:
            results.append("<li><strong>"+html.escape(d["name"])+"</strong>: ошибка "+html.escape(str(exc.detail))+"; требуется проверить документ.</li>")
        except Exception as exc:
            logging.exception("Bulk pending assignment failed (%s)",type(exc).__name__)
            results.append("<li><strong>"+html.escape(d["name"])+"</strong>: ошибка обработки; требуется повторная проверка.</li>")
    body='<p><a href="/families/'+str(fid)+'/inbox">← Ко входящим</a></p><h2>Результат массового назначения</h2><div class="card"><ul>'+''.join(results)+'</ul></div>'
    return page("Массовое назначение",body)

@app.get("/families/{fid}/inbox/{pending_id}/preview")
def preview_pending_document(fid:int,pending_id:int,uid:int=Depends(current_user)):
    family(fid,uid)
    d=db.get_pending_doc(fid,pending_id)
    if not d: raise HTTPException(404,"Документ не найден")
    ext=Path(d["name"]).suffix.lower()
    media={".pdf":"application/pdf",".jpg":"image/jpeg",".jpeg":"image/jpeg",".png":"image/png",".webp":"image/webp",".bmp":"image/bmp",".tif":"image/tiff",".tiff":"image/tiff"}.get(ext)
    if not media: raise HTTPException(415,"Предпросмотр формата недоступен")
    return Response(content=d["file_bytes"],media_type=media,headers={"Content-Disposition":"inline; filename*=UTF-8''"+__import__("urllib.parse",fromlist=["quote"]).quote(d["name"])})

@app.get("/families/{fid}/inbox/{pending_id}", response_class=HTMLResponse)
def review_pending_document(fid:int,pending_id:int,uid:int=Depends(current_user)):
    family(fid,uid)
    d=db.get_pending_doc(fid,pending_id)
    if not d: raise HTTPException(404,"Документ не найден во входящих")
    patients=db.patient_records(fid)
    from AIAnalise import DOCUMENT_TYPE_RULES
    kinds=["не определено"]+sorted(DOCUMENT_TYPE_RULES.keys())
    patient_options="".join('<option value="'+html.escape(p["name"],quote=True)+'">'+html.escape(p["name"])+(' · рожд. '+html.escape(p["birth_date"]) if p.get("birth_date") else '')+'</option>' for p in patients)
    labels={"лабораторный отчёт":"Анализы","заключение УЗИ":"УЗИ","заключение КТ":"КТ","заключение МРТ":"МРТ","рентгенологическое заключение":"Рентген","направление":"Направление","протокол осмотра или приёма":"Приём врача","консультация специалиста":"Консультация врача","выписной эпикриз":"Выписка из стационара","выписка из медицинской карты":"Выписка из карты","назначение или рецепт":"Назначение / рецепт","заключение ЭКГ":"ЭКГ","эндоскопическое заключение":"Эндоскопия (ФГДС / колоноскопия)","патоморфологическое заключение":"Гистология / биопсия","операционный протокол":"Операция","медицинская справка":"Медицинская справка","справка о временной нетрудоспособности":"Больничный / справка","вакцинальный документ":"Прививки","история развития ребёнка":"История развития ребёнка","контрольная карта диспансерного наблюдения":"Диспансерное наблюдение","медицинская карта или наблюдение":"Медицинская карта","документ по беременности и родам":"Беременность и роды","медицинское свидетельство о рождении":"Свидетельство о рождении","медицинское свидетельство о смерти":"Свидетельство о смерти","санаторно-курортная документация":"Санаторий / реабилитация","не определено":"Не определено"}
    kind_options="".join('<option value="'+html.escape(k,quote=True)+'"'+(' selected' if k==d["analysis"].get("primary_type") else '')+'>'+html.escape(labels.get(k,k[:1].upper()+k[1:]))+'</option>' for k in kinds)
    ext=Path(d["name"]).suffix.lower()
    preview_url=f"/families/{fid}/inbox/{pending_id}/preview"
    if ext in {".jpg",".jpeg",".png",".webp",".bmp",".tif",".tiff"}:
        preview=f'<a class="document-preview-link" href="{preview_url}" target="_blank" rel="noopener" aria-label="Открыть изображение в полном размере"><img class="preview-image" src="{preview_url}" alt="Предпросмотр документа"><span>Нажмите, чтобы открыть полностью ↗</span></a>'
    elif ext==".pdf":
        preview=f'<div class="pdf-preview"><div class="pdf-preview-toolbar">Предпросмотр PDF · прокрутите документ ниже</div><iframe src="{preview_url}#view=FitH" title="Предпросмотр PDF" loading="lazy"></iframe><p><a href="{preview_url}" target="_blank" rel="noopener">Открыть PDF отдельно ↗</a></p></div>'
    else:
        preview=""
    body=f'<p><a href="/families/{fid}/inbox">← К входящим</a></p><h2>Классификация документа</h2><div class="card pending-review-card"><strong>Файл:</strong> {html.escape(d["name"])}{preview}<details><summary>Показать OCR-текст</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{html.escape(d["text"][:12000])}</pre></details></div>'
    body+=f'<p><a href="/families/{fid}/patients/new">＋ Добавить пациента</a></p>'
    body+=f'<form class="pending-classification-form" method="post" action="/families/{fid}/inbox/{pending_id}/assign"><label>Пациент<br><select name="patient" required>{patient_options}</select></label><label>Тип документа<br><select name="kind" required>{kind_options}</select></label><label>Название в архиве<br><input name="title" required maxlength="180" value="{html.escape(str(d["analysis"].get("display_title") or d["analysis"].get("primary_type") or d["name"]),quote=True)}"></label><label>Дата документа (ДД-ММ-ГГГГ)<br><input name="date" placeholder="17-03-2025" maxlength="10"></label><p><button type="submit">Сохранить в историю пациента</button></p></form>'
    body+=f'<form class="pending-delete-form" method="post" action="/families/{fid}/inbox/{pending_id}/delete" onsubmit="return confirm(\'Удалить этот документ из входящих без возможности восстановления?\')"><input type="hidden" name="confirm" value="yes"><button type="submit">Удалить документ</button></form>'
    return page("Ручная классификация",body)


@app.post("/families/{fid}/inbox/{pending_id}/delete", response_class=HTMLResponse)
def delete_pending_document(fid:int,pending_id:int,confirm:str=Form(...),uid:int=Depends(current_user)):
    family(fid,uid)
    if confirm != "yes":
        raise HTTPException(400,"Удаление не подтверждено")
    d=db.get_pending_doc(fid,pending_id)
    if not d:
        raise HTTPException(404,"Документ не найден во входящих")
    # Only remove a record that is still in the pending inbox; do not touch
    # patient archive files or shared storage paths here.
    db.delete_pending_doc(fid,pending_id)
    return RedirectResponse(f"/families/{fid}/inbox?deleted=1",status_code=303)

@app.post("/families/{fid}/inbox/{pending_id}/assign", response_class=HTMLResponse)
def assign_pending_document(fid:int,pending_id:int,patient:str=Form(...),kind:str=Form(...),title:str=Form(...),date:str=Form(""),uid:int=Depends(current_user)):
    family(fid,uid)
    storage_backend = "local" if is_demo_user(uid) else STORAGE_BACKEND
    if is_demo_user(uid): tenancy.refresh_demo_expiry(fid)
    d=db.get_pending_doc(fid,pending_id)
    if not d: raise HTTPException(404,"Документ не найден во входящих")
    if patient not in db.patients(fid): raise HTTPException(400,"Выбранный пациент не найден")
    from AIAnalise import DOCUMENT_TYPE_RULES, DOCUMENT_TAXONOMY
    from datetime import datetime
    if kind!="не определено" and kind not in DOCUMENT_TYPE_RULES: raise HTTPException(400,"Неизвестный тип документа")
    title=" ".join((title or "").split()).strip()[:180]
    if not title: raise HTTPException(400,"Введите название документа")
    date=(date or "").strip()
    if date:
        try: date=datetime.strptime(date,"%d-%m-%Y").strftime("%d-%m-%Y")
        except ValueError: raise HTTPException(400,"Дата должна быть в формате ДД-ММ-ГГГГ")
    if db.document_exists(fid,patient,d["digest"]):
        db.delete_pending_doc(fid,pending_id)
        return RedirectResponse(f"/families/{fid}/inbox",status_code=303)
    token=tenancy.get_yadisk_token(fid) if storage_backend=="yandex" else None
    if storage_backend=="yandex" and not token: raise HTTPException(400,"Сначала подключите Яндекс Диск")
    analysis=d["analysis"] or {}
    analysis.update({"primary_type":kind,"primary_category":DOCUMENT_TAXONOMY.get(kind,{}).get("category","не определено"),
      "taxonomy_path":[DOCUMENT_TAXONOMY.get(kind,{}).get("category","не определено"),kind] if kind in DOCUMENT_TAXONOMY else [],
      "document_types":[kind] if kind!="не определено" else [],"types":[kind] if kind!="не определено" else [],
      "confidence":"manual","review_required":kind=="не определено","display_title":title})
    ext=Path(d["name"]).suffix.lower()
    stored=f"{Path(format_filename(patient,kind,date,ext)).stem}_{d['digest'][:8]}.{normalize_extension(d['name'])}"
    ocr_stored=Path(stored).stem+".txt"
    with tempfile.TemporaryDirectory() as td:
        local=Path(td)/Path(d["name"]).name
        local.write_bytes(d["file_bytes"])
        if storage_backend=="local":
            remote_path=save_local_file(fid,patient,stored,local)
            ocr_tmp=Path(td)/ocr_stored; ocr_tmp.write_text(d["text"],encoding="utf-8")
            ocr_path=save_local_file(fid,patient,ocr_stored,ocr_tmp)
            remote,oremote=str(remote_path),str(ocr_path)
        else:
            disk=YaDiskClient(token); folder=f"{ROOT}/family_{fid}/{safe_name(patient)}"
            docs,ocr=folder+"/docs",folder+"/OCR"; disk.ensure_folder(docs); disk.ensure_folder(ocr)
            remote,oremote=docs+"/"+stored,ocr+"/"+ocr_stored
            disk.upload_file(str(local),remote)
            ocr_tmp=Path(td)/ocr_stored; ocr_tmp.write_text(d["text"],encoding="utf-8"); disk.upload_file(str(ocr_tmp),oremote)
        if not db.add_doc(fid,patient,stored,kind,date,remote,oremote,d["text"],extract_keywords(d["text"],analysis),d["digest"],analysis=analysis):
            raise HTTPException(409,"Не удалось добавить документ в историю; запись во входящих сохранена")
        db.delete_pending_doc(fid,pending_id)
        if storage_backend=="yandex":
            hp=Path(td)/"history.txt"; hp.write_text(db.history(fid,patient),encoding="utf-8"); disk.upload_file(str(hp),folder+"/history.txt")
    return RedirectResponse(f"/families/{fid}/patients/{patient}",status_code=303)

@app.post("/families/{fid}/patients/{patient}/upload",response_class=HTMLResponse)
def upload(fid:int,patient:str,file:UploadFile=File(...),ai_consent:bool=Form(False),uid:int=Depends(current_user)):
    family(fid,uid)
    storage_backend = "local" if is_demo_user(uid) else STORAGE_BACKEND
    upload_limit_mb = min(MAX_UPLOAD_MB, DEMO_MAX_UPLOAD_MB) if is_demo_user(uid) else MAX_UPLOAD_MB
    if is_demo_user(uid):
        tenancy.refresh_demo_expiry(fid)
        enforce_demo_document_quota(fid, 1)
    if patient not in db.patients(fid): raise HTTPException(404,"Пациент не найден")
    if storage_backend not in {"local","yandex"}: raise HTTPException(503,"Неизвестный backend хранения")
    token=tenancy.get_yadisk_token(fid) if storage_backend == "yandex" else None
    if storage_backend == "yandex" and not token: raise HTTPException(400,"Сначала подключите Яндекс Диск")
    name=Path(file.filename or "document.bin").name
    ext=Path(name).suffix.lower()
    if ext not in ALLOWED: raise HTTPException(400,"Формат файла не поддерживается")
    with tempfile.TemporaryDirectory() as td:
        local=Path(td)/name
        size=0
        with local.open("wb") as out:
            while True:
                chunk=file.file.read(1024*1024)
                if not chunk: break
                size+=len(chunk)
                if size>upload_limit_mb*1024*1024: raise HTTPException(413,f"Файл больше {upload_limit_mb} МБ")
                out.write(chunk)
        saved_paths=[]
        try:
            text=ocr_file(str(local))
            analysis=analyze_document(text)
            if ai_consent and os.getenv("AI_CLASSIFICATION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}:
                try:
                    analysis=classify_with_ai(text, analysis)
                except Exception as exc:
                    logging.warning("AI classification unavailable (%s); retaining local classification", type(exc).__name__)
            kind=analysis["primary_type"]
            keywords=extract_keywords(text,analysis)
            date=parse_date_from_text(text)
            digest=hashlib.sha256(local.read_bytes()).hexdigest()
            ex=normalize_extension(name)
            if db.document_exists(fid,patient,digest):
                return page("Дубликат",f'<p>Этот файл уже сохранён в архиве.</p><p><a href="/families/{fid}/patients/{html.escape(patient,quote=True)}">Назад к пациенту</a></p>')
            stored=f"{Path(format_filename(patient,kind,date,ex)).stem}_{digest[:8]}.{ex}"
            ocr_stored=Path(stored).stem+".txt"
            if storage_backend == "local":
                saved_path=save_local_file(fid,patient,stored,local); saved_paths.append(saved_path)
                ocr_tmp=Path(td)/ocr_stored; ocr_tmp.write_text(text,encoding="utf-8")
                saved_paths.append(save_local_file(fid,patient,ocr_stored,ocr_tmp))
                remote=str(saved_path); oremote=str(saved_path.parent/ocr_stored)
            else:
                disk=YaDiskClient(token); folder=f"{ROOT}/family_{fid}/{safe_name(patient)}"
                docs,ocr=folder+"/docs",folder+"/OCR"
                disk.ensure_folder(docs); disk.ensure_folder(ocr)
                remote,oremote=docs+"/"+stored,ocr+"/"+ocr_stored
                disk.upload_file(str(local),remote)
                with tempfile.TemporaryDirectory() as od:
                    op=Path(od)/"ocr.txt"; op.write_text(text,encoding="utf-8"); disk.upload_file(str(op),oremote)
            if not db.add_doc(fid,patient,stored,kind,date,remote,oremote,text,keywords,digest,analysis=analysis):
                if storage_backend == "local":
                    for candidate in saved_paths:
                        try: candidate.unlink()
                        except FileNotFoundError: pass
                return page("Дубликат",'<p>Файл уже есть в индексе.</p><p><a href="/">На главную</a></p>')
            if storage_backend == "yandex":
                with tempfile.TemporaryDirectory() as hd:
                    hp=Path(hd)/"history.txt"; hp.write_text(db.history(fid,patient),encoding="utf-8"); disk.upload_file(str(hp),folder+"/history.txt")
            status="Требуется проверить тип вручную." if analysis["review_required"] else "Тип определён автоматически; проверьте по оригиналу."
            other_types=", ".join(analysis["document_types"]) or "не определено"
            return page("Сохранено",f'<p>Документ сохранён.</p><p>Основной тип: {html.escape(kind)}.</p><p>Типы документа: {html.escape(other_types)}.</p><p>Уверенность: {html.escape(analysis["confidence"])}.</p><p>{html.escape(status)}</p><p><a href="/families/{fid}/patients/{html.escape(patient,quote=True)}">Назад к пациенту</a></p>')
        except HTTPException: raise
        except Exception as e:
            if storage_backend == "local":
                for candidate in saved_paths:
                    try: candidate.unlink()
                    except FileNotFoundError: pass
            logging.exception("Web upload failed (%s)",type(e).__name__)
            raise HTTPException(502,f"Не удалось обработать документ ({type(e).__name__}). Проверьте OCR и выбранное хранилище.") from e

@app.get("/families/{fid}/connect-disk")
def connect_disk(fid:int,uid:int=Depends(current_user)):
    if is_demo_user(uid): raise HTTPException(403,"В демо-режиме доступно только локальное временное хранилище")
    family(fid,uid)
    if tenancy.role_for_user(fid,uid) not in ("owner","admin"): raise HTTPException(403,"Нет прав")
    cid=os.getenv("YANDEX_CLIENT_ID","").strip(); secret=os.getenv("YANDEX_CLIENT_SECRET","").strip(); uri=os.getenv("YANDEX_REDIRECT_URI","").strip()
    if not cid or not secret or not uri.startswith("https://"): raise HTTPException(503,"Настройте Yandex OAuth и HTTPS callback")
    state=tenancy.create_oauth_state(fid,uid)
    params={"response_type":"code","client_id":cid,"redirect_uri":uri,"scope":"cloud_api:disk.read cloud_api:disk.write","state":state}
    return RedirectResponse("https://oauth.yandex.ru/authorize?"+urlencode(params),status_code=303)

@app.get("/oauth/yandex/callback",response_class=HTMLResponse)
def yandex_callback(code:str="",state:str="",error:str=""):
    if error: return page("Отменено","<p>Авторизация отменена. Вернитесь в архив.</p>",400)
    if not code or not state: return page("Ошибка","<p>Не хватает параметров авторизации.</p>",400)
    pending=tenancy.consume_oauth_state(state)
    if not pending: return page("Ссылка истекла","<p>Ссылка истекла или использована. Начните подключение заново.</p>",400)
    if tenancy.role_for_user(pending["family_id"],pending["telegram_id"]) not in ("owner","admin"): return page("Нет доступа","<p>Нет прав на этот архив.</p>",403)
    payload={"grant_type":"authorization_code","code":code,"client_id":os.getenv("YANDEX_CLIENT_ID","").strip(),"client_secret":os.getenv("YANDEX_CLIENT_SECRET","").strip(),"redirect_uri":os.getenv("YANDEX_REDIRECT_URI","").strip()}
    try:
        r=requests.post("https://oauth.yandex.ru/token",data=payload,timeout=20); data=r.json()
        if r.status_code>=400 or not data.get("access_token"): return page("Ошибка Яндекса","<p>Яндекс не выдал токен. Проверьте настройки OAuth.</p>",502)
        tenancy.save_yadisk_token(pending["family_id"],data["access_token"],"Подключённый Яндекс Диск")
        return page("Подключено","<p>Яндекс Диск подключён. <a href='/'>Вернуться в архив</a></p>")
    except Exception as e:
        logging.exception("OAuth callback failed (%s)",type(e).__name__)
        return page("Ошибка","<p>Не удалось подключить Яндекс Диск.</p>",502)

# AI-assisted retrieval routes are isolated from Telegram bot handlers.
from assistant_routes import install_assistant_routes
install_assistant_routes(app, current_user, family)