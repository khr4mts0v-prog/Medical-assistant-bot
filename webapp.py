"""Test web interface for Medical Archive. MUST be exposed only behind HTTPS."""
import hashlib, hmac, html, logging, os, tempfile
from pathlib import Path
from urllib.parse import urlencode
import requests
from fastapi import FastAPI, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db, tenancy
from cloud import YaDiskClient
from local_storage import save_file as save_local_file
from ocr import ocr_file
from AIAnalise import classify_document, extract_keywords
from utils import format_filename, normalize_extension, parse_date_from_text, safe_name

app=FastAPI(title="Medical Archive", docs_url=None, redoc_url=None)
security=HTTPBasic()
WEB_USERNAME=os.getenv("WEB_USERNAME","").strip()
WEB_PASSWORD=os.getenv("WEB_PASSWORD","")
ROOT=os.getenv("YANDEX_ROOT_FOLDER","MedArchive").strip("/")
STORAGE_BACKEND=os.getenv("DOCUMENT_STORAGE_BACKEND","local").strip().lower()
MAX_UPLOAD_MB=max(1,int(os.getenv("MAX_UPLOAD_MB","20")))
ALLOWED={".pdf",".png",".jpg",".jpeg",".webp",".tif",".tiff",".bmp"}
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(message)s")

def current_user(credentials: HTTPBasicCredentials=Depends(security))->int:
    if not WEB_USERNAME or not WEB_PASSWORD:
        raise HTTPException(503,"Web login is not configured")
    u=hmac.compare_digest(credentials.username.encode(),WEB_USERNAME.encode())
    p=hmac.compare_digest(credentials.password.encode(),WEB_PASSWORD.encode())
    if not (u and p):
        raise HTTPException(401,"Invalid username or password",headers={"WWW-Authenticate":'Basic realm="Medical Archive"'})
    return -(int(hashlib.sha256(WEB_USERNAME.encode()).hexdigest()[:12],16) or 1)

def page(title,body,status=200):
    return HTMLResponse("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>"""+html.escape(title)+""" · Медицинский архив</title><style>
body{max-width:850px;margin:auto;padding:18px;font:16px/1.5 system-ui,sans-serif}h1{font-size:1.5rem}h2{font-size:1.15rem}.card{border:1px solid #8888;border-radius:12px;padding:14px;margin:12px 0}input,select,button{font:inherit;max-width:100%;padding:9px;margin:4px 0}input[type=text],input[type=search]{width:min(100%,440px)}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.muted{opacity:.7}.warn{border-left:4px solid #b8860b;padding:8px 12px}a{overflow-wrap:anywhere}</style></head><body><h1>Медицинский архив</h1>"""+body+"""<p class="muted"><small>Тестовый MVP. Не заменяет врача.</small></p></body></html>""",status_code=status)

def family(fid,uid):
    if not tenancy.role_for_user(fid,uid): raise HTTPException(403,"Нет доступа к этому семейному архиву")
    f=tenancy.get_family(fid)
    if not f: raise HTTPException(404,"Архив не найден")
    return f

def home_url(fid=None): return RedirectResponse("/" if fid is None else f"/?family_id={int(fid)}",status_code=303)

@app.get("/",response_class=HTMLResponse)
def home(family_id:int|None=None,uid:int=Depends(current_user)):
    fs=tenancy.families_for_user(uid)
    if family_id is not None and not tenancy.role_for_user(family_id,uid): raise HTTPException(403,"Нет доступа")
    f=tenancy.get_family(family_id) if family_id is not None else (tenancy.get_family(fs[0]["id"]) if fs else None)
    b=['<p>Веб-интерфейс тестового архива. Вход защищён паролем; использовать только через HTTPS.</p><div class="card"><h2>Семейные архивы</h2>']
    if fs:
        b.append('<form class="row" method="get"><select name="family_id">')
        for x in fs: b.append(f'<option value="{x["id"]}"{" selected" if f and x["id"]==f["id"] else ""}>{html.escape(x["name"])}</option>')
        b.append('</select><button>Открыть</button></form>')
    else: b.append('<p>Архивов пока нет.</p>')
    b.append('<form method="post" action="/families"><label>Название архива<br><input name="name" required maxlength="80"></label> <button>Создать архив</button></form></div>')
    if f:
        fid=f["id"]
        b.append(f'<div class="card"><h2>Архив: {html.escape(f["name"])}</h2><p>Хранение документов: {"локально на VPS" if STORAGE_BACKEND == "local" else "Яндекс Диск"}</p>')
        if STORAGE_BACKEND == "yandex" and not tenancy.disk_connected(fid):
            b.append(f'<p><a href="/families/{fid}/connect-disk">Подключить Яндекс Диск</a></p>')
        b.append(f'<form method="post" action="/families/{fid}/patients"><label>Имя пациента<br><input name="name" required maxlength="100"></label> <button>Добавить</button></form><h2>Пациенты</h2>')
        ps=db.patients(fid)
        if not ps: b.append('<p>Пациентов пока нет.</p>')
        for p in ps:
            ep=html.escape(p,quote=True)
            b.append(f'<div class="card"><strong>{html.escape(p)}</strong> · документов: {db.document_count(fid,p)}<form class="row" method="get" action="/families/{fid}/patients/{ep}"><input type="search" name="q" placeholder="Поиск по документам"><button>Искать</button></form><a href="/families/{fid}/patients/{ep}">История документов</a></div>')
        b.append('</div>')
    b.append('<div class="warn"><strong>Важно:</strong> не загружайте реальные медицинские документы до настройки резервного копирования и полной проверки прав доступа.</div>')
    return page("Главная","".join(b))

@app.post("/families")
def create_family(name:str=Form(...),uid:int=Depends(current_user)):
    try: fid=tenancy.create_family(name,uid)
    except ValueError as e: raise HTTPException(400,str(e))
    return home_url(fid)

@app.post("/families/{fid}/patients")
def add_patient(fid:int,name:str=Form(...),uid:int=Depends(current_user)):
    family(fid,uid); db.add_patient(fid,name); return home_url(fid)

@app.get("/families/{fid}/patients/{patient}",response_class=HTMLResponse)
def patient_page(fid:int,patient:str,q:str="",uid:int=Depends(current_user)):
    family(fid,uid)
    if patient not in db.patients(fid): raise HTTPException(404,"Пациент не найден")
    rows=db.search(fid,patient,q)
    b=[f'<p><a href="/?family_id={fid}">← К архиву</a></p><h2>{html.escape(patient)}</h2><p>Найдено документов: {len(rows)}</p>']
    if STORAGE_BACKEND == "yandex" and not tenancy.disk_connected(fid):
        b.append(f'<p><a href="/families/{fid}/connect-disk">Подключить Яндекс Диск</a></p>')
    else:
        b.append(f'<div class="card"><h2>Загрузить документ</h2><form method="post" enctype="multipart/form-data" action="/families/{fid}/patients/{html.escape(patient,quote=True)}/upload"><input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" required><button>Загрузить и распознать</button></form><small>PDF/изображение до {MAX_UPLOAD_MB} МБ. Файл сохранится {"на VPS" if STORAGE_BACKEND == "local" else "на Яндекс Диск"}.</small></div>')
    b.append('<div class="card"><h2>Документы</h2>')
    if not rows: b.append('<p>Документы не найдены.</p>')
    for d in rows:
        link = f'<p><a href="/families/{fid}/documents/{int(d["id"])}">Открыть оригинал</a></p>' if STORAGE_BACKEND == "local" and d.get("remote") else ""
        b.append(f'<div class="card"><strong>{html.escape(str(d.get("name") or "Документ"))}</strong><br>Тип: {html.escape(str(d.get("kind") or "—"))} · Дата: {html.escape(str(d.get("date") or "—"))}<p>{html.escape((d.get("text") or "")[:600])}</p>{link}<small>{html.escape(str(d.get("remote") or ""))}</small></div>')
    b.append('</div>')
    return page("Пациент","".join(b))

@app.get("/families/{fid}/documents/{doc_id}")
def download_document(fid:int,doc_id:int,uid:int=Depends(current_user)):
    family(fid,uid)
    if STORAGE_BACKEND != "local":
        raise HTTPException(404,"Локальные документы не используются")
    d=db.get_doc(fid,doc_id)
    if not d:
        raise HTTPException(404,"Документ не найден")
    path=Path(str(d.get("remote") or "")).resolve()
    from local_storage import DATA_ROOT
    if path != DATA_ROOT and DATA_ROOT not in path.parents:
        raise HTTPException(404,"Документ не найден")
    if not path.is_file():
        raise HTTPException(404,"Файл отсутствует в локальном хранилище")
    return FileResponse(path,filename=str(d.get("name") or path.name),media_type="application/octet-stream")

@app.post("/families/{fid}/patients/{patient}/upload",response_class=HTMLResponse)
def upload(fid:int,patient:str,file:UploadFile=File(...),uid:int=Depends(current_user)):
    family(fid,uid)
    if patient not in db.patients(fid): raise HTTPException(404,"Пациент не найден")
    if STORAGE_BACKEND not in {"local","yandex"}:
        raise HTTPException(503,"Неизвестный backend хранения")
    token=tenancy.get_yadisk_token(fid) if STORAGE_BACKEND == "yandex" else None
    if STORAGE_BACKEND == "yandex" and not token:
        raise HTTPException(400,"Сначала подключите Яндекс Диск")
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
                if size>MAX_UPLOAD_MB*1024*1024: raise HTTPException(413,f"Файл больше {MAX_UPLOAD_MB} МБ")
                out.write(chunk)
        saved_path = None
        try:
            text=ocr_file(str(local)); kind=classify_document(text); keywords=extract_keywords(text); date=parse_date_from_text(text)
            digest=hashlib.sha256(local.read_bytes()).hexdigest(); ex=normalize_extension(name)
            stored=f"{Path(format_filename(patient,kind,date,ex)).stem}_{digest[:8]}.{ex}"
            ocr_stored=Path(stored).stem+".txt"
            if STORAGE_BACKEND == "local":
                saved_path = save_local_file(fid,patient,stored,local)
                ocr_path = save_local_file(fid,patient,ocr_stored,Path(td)/"unused") if False else None
                ocr_tmp=Path(td)/ocr_stored
                ocr_tmp.write_text(text,encoding="utf-8")
                save_local_file(fid,patient,ocr_stored,ocr_tmp)
                remote=str(saved_path)
                oremote=str(saved_path.parent/ocr_stored)
            else:
                disk=YaDiskClient(token); folder=f"{ROOT}/family_{fid}/{safe_name(patient)}"
                docs,ocr=folder+"/docs",folder+"/OCR"
                disk.ensure_folder(docs); disk.ensure_folder(ocr)
                remote,oremote=docs+"/"+stored,ocr+"/"+ocr_stored
                disk.upload_file(str(local),remote)
                with tempfile.TemporaryDirectory() as od:
                    op=Path(od)/"ocr.txt"; op.write_text(text,encoding="utf-8"); disk.upload_file(str(op),oremote)
            if not db.add_doc(fid,patient,stored,kind,date,remote,oremote,text,keywords,digest):
                if STORAGE_BACKEND == "local":
                    for candidate in (Path(remote),Path(oremote)):
                        try: candidate.unlink()
                        except FileNotFoundError: pass
                return page("Дубликат",'<p>Файл уже есть в индексе.</p><p><a href="/">На главную</a></p>')
            if STORAGE_BACKEND == "yandex":
                with tempfile.TemporaryDirectory() as hd:
                    hp=Path(hd)/"history.txt"; hp.write_text(db.history(fid,patient),encoding="utf-8"); disk.upload_file(str(hp),folder+"/history.txt")
            return page("Сохранено",f'<p>Документ сохранён. Тип: {html.escape(kind)}; дата: {html.escape(date)}; символов OCR: {len(text)}.</p><p><a href="/families/{fid}/patients/{html.escape(patient,quote=True)}">Назад к пациенту</a></p>')
        except HTTPException: raise
        except Exception as e:
            logging.exception("Web upload failed (%s)",type(e).__name__)
            raise HTTPException(502,f"Не удалось обработать документ ({type(e).__name__}). Проверьте OCR и выбранное хранилище.") from e

@app.get("/families/{fid}/connect-disk")
def connect_disk(fid:int,uid:int=Depends(current_user)):
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
