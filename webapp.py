"""Test web interface for Medical Archive. MUST be exposed only behind HTTPS."""
import hashlib, hmac, html, logging, os, tempfile
from pathlib import Path
from urllib.parse import urlencode
import requests
from fastapi import FastAPI, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import database as db, tenancy
from cloud import YaDiskClient
from local_storage import save_file as save_local_file
from ocr import ocr_file
from AIAnalise import analyze_document, extract_keywords
from utils import format_filename, normalize_extension, parse_date_from_text, safe_name
from document_metadata import extract_registered_patient, extract_patient_birth_date

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
    return HTMLResponse("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>"""+html.escape(title)+""" · Медицинский архив</title><style>
:root{color-scheme:light dark;--bg:#fff;--fg:#171717;--card:#fff;--line:#d1d5db;--muted:#626262;--field:#fff;--accent:#166534;--warn:#b8860b} @media(prefers-color-scheme:dark){:root{--bg:#101114;--fg:#f2f2f2;--card:#191b20;--line:#3c4048;--muted:#b4b7bf;--field:#22252b;--accent:#4ade80;--warn:#eab308}}*{box-sizing:border-box}body{max-width:850px;margin:auto;padding:18px;font:16px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}h1{font-size:1.5rem}h2{font-size:1.15rem}.card{border:1px solid var(--line);border-radius:12px;padding:14px;margin:12px 0;background:var(--card)}input,select,button{font:inherit;max-width:100%;padding:9px;margin:4px 0;border:1px solid var(--line);border-radius:8px;background:var(--field);color:var(--fg)}button{cursor:pointer}input[type=text],input[type=search]{width:min(100%,440px)}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.muted{color:var(--muted)}.warn{border-left:4px solid var(--warn);padding:8px 12px}a{overflow-wrap:anywhere;color:inherit}.home-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:14px 0}.home-action{display:flex;aspect-ratio:1/0.82;align-items:center;justify-content:center;min-height:125px;padding:12px;border-radius:16px;border:1px solid var(--line);background:var(--card);text-align:center;text-decoration:none;font-weight:700;font-size:1.02rem}.home-action.primary{background:var(--accent);color:#fff;border-color:var(--accent)}.pending-thumbs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:12px 0}.pending-thumb{display:block;min-width:0;text-decoration:none}.pending-thumb img,.file-thumb{display:flex;width:100%;height:90px;object-fit:cover;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:8px;background:var(--field)}.pending-thumb span:last-child{display:block;font-size:.78rem;overflow-wrap:anywhere;max-height:2.6em;overflow:hidden}.pending-more{align-self:center}.preview-image{display:block;width:100%;max-height:60vh;object-fit:contain;border:1px solid var(--line);border-radius:10px;margin:12px 0}.upload-item{border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}@media(max-width:520px){body{padding:12px}.home-actions{grid-template-columns:repeat(2,minmax(0,1fr))}.home-action{min-height:125px;font-size:.95rem;padding:8px}.card{padding:12px}}.upload-top{display:flex;gap:10px;align-items:center}.upload-name{flex:1;min-width:0;overflow-wrap:anywhere}.upload-remove{font-size:22px;line-height:1;min-width:42px}.upload-track{height:7px;background:var(--line);border-radius:99px;overflow:hidden;margin-top:9px}.upload-fill{height:100%;width:0;background:var(--accent);transition:width .12s}.upload-status{font-size:.9rem;color:var(--muted)}.patient-heading{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.button-link{display:inline-block;border:1px solid var(--line);border-radius:8px;padding:8px 11px;text-decoration:none}.tabs{display:flex;gap:8px;border-bottom:1px solid var(--line);margin:14px 0}.tab{padding:10px 13px;text-decoration:none;border-bottom:3px solid transparent}.tab.active{border-color:var(--accent);font-weight:700}.patient-search label{display:block;font-weight:600}.timeline-date{margin:20px 0 8px}.document-row{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:12px;border:1px solid var(--line);border-radius:10px;margin:8px 0;background:var(--card)}.document-main{min-width:0;overflow-wrap:anywhere}.tree-group{border:1px solid var(--line);border-radius:10px;padding:12px;margin:10px 0}.tree-group summary{cursor:pointer;font-weight:700}.notice-success{border-left:4px solid #16865b;padding:10px 14px;background:var(--card);border-radius:8px}.danger{border-color:#b91c1c;color:#b91c1c}@media(max-width:520px){.document-row{align-items:flex-start;flex-direction:column}.tabs{gap:2px}.tab{padding:9px 7px}} </style></head><body><h1>Медицинский архив</h1>"""+body+"""<p class="muted"><small>Тестовый MVP. Не заменяет врача.</small></p></body></html>""",status_code=status)

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
    if not tenancy.role_for_user(fid,uid): raise HTTPException(403,"Нет доступа к этому семейному архиву")
    f=tenancy.get_family(fid)
    if not f: raise HTTPException(404,"Архив не найден")
    return f

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
def home(family_id:int|None=None,uid:int=Depends(current_user)):
    fs=tenancy.families_for_user(uid)
    if family_id is not None and not tenancy.role_for_user(family_id,uid): raise HTTPException(403,"Нет доступа")
    f=tenancy.get_family(family_id) if family_id is not None else (tenancy.get_family(fs[0]["id"]) if fs else None)
    b=[]
    if fs:
        selected_for_actions = f["id"] if f else fs[0]["id"]
        pending_for_actions = len(db.pending_documents(selected_for_actions))
        patient_count = len(db.patients(selected_for_actions))
        b.append('<nav class="home-actions" aria-label="Основные действия"><button class="home-action primary" type="button" id="home-upload-trigger">＋ Загрузить документы</button><a class="home-action" href="/families/' + str(selected_for_actions) + '/inbox">Входящие · на проверку (' + str(pending_for_actions) + ')</a><a class="home-action" href="#patients">История пациентов (' + str(patient_count) + ')</a><a class="home-action" href="#family-settings">Настройки архива</a></nav>')
        b.append('<form class="card row" method="get" action="/search"><input type="hidden" name="family_id" value="' + str(selected_for_actions) + '"><label for="archive-search">Поиск по архиву</label><input id="archive-search" type="search" name="q" placeholder="Например: Саша анализы" required><button type="submit">Найти документы</button></form>')
    # Inbox-first workflow: files can be uploaded before opening a patient record.
    if fs:
        selected_fid = f["id"] if f else fs[0]["id"]
        upload_options = "".join(
            '<option value="' + str(x["id"]) + '"' + (' selected' if x["id"] == selected_fid else '') + '>' + html.escape(x["name"]) + '</option>'
            for x in fs
        )
        b.append(
            '<div class="card" id="quick-upload"><h2>Быстрая загрузка документов</h2>'
            '<p class="muted">Статус обновляется после передачи файла и завершения распознавания и классификации.</p>'
            '<select id="upload-family" hidden aria-hidden="true">' + upload_options + '</select>'
            '<input id="upload-files" type="file" accept="image/*,application/pdf,.tif,.tiff,.bmp" multiple hidden>' '<button type="button" id="choose-files">＋ Выбрать документы</button>'
            '<div id="upload-queue" aria-live="polite"></div>'
            '<small>До ' + str(MAX_UPLOAD_MB) + ' МБ на файл. OCR и классификация выполняются на сервере после передачи.</small></div>'
            '<script>(function(){const input=document.getElementById("upload-files"),queue=document.getElementById("upload-queue"),family=document.getElementById("upload-family");let items=[],seq=0;document.getElementById("home-upload-trigger").addEventListener("click",function(){input.click()});'
            'function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]})}'
            'function render(){queue.innerHTML=items.map(function(x){return \'<div class="upload-item"><div class="upload-top"><div class="upload-name"><strong>\'+esc(x.file.name)+\'</strong><div class="upload-status">\'+(x.file.size/1048576).toFixed(2)+\' МБ · \'+esc(x.status)+\'</div></div><button class="upload-remove" type="button" data-remove="\'+x.id+\'" aria-label="Убрать файл из списка">×</button></div><div class="upload-track"><div class="upload-fill" style="width:\'+x.progress+\'%"></div></div><small>\'+x.progress+\'%</small></div>\'}).join("");queue.querySelectorAll("[data-remove]").forEach(function(b){b.addEventListener("click",function(){const id=Number(b.dataset.remove),item=items.find(function(x){return x.id===id});if(item&&item.xhr){item.cancelled=true;item.status="Отменено в браузере; результат сервера неизвестен";item.xhr.abort()}items=items.filter(function(x){return x.id!==id});render()})})}window.addEventListener("beforeunload",function(e){if(items.some(function(x){return x.xhr&&!x.cancelled})){e.preventDefault();e.returnValue=""}});'
            'function upload(item){item.status="Загрузка";const xhr=new XMLHttpRequest(),form=new FormData();item.xhr=xhr;form.append("family_id",family.value);form.append("files",item.file,item.file.name);xhr.open("POST","/upload");xhr.upload.onprogress=function(e){if(e.lengthComputable){item.progress=Math.round(e.loaded/e.total*100);item.status=item.progress>=100?"Передан · обработка на сервере":"Загрузка";render()}};xhr.onload=function(){item.xhr=null;if(item.cancelled)return;item.progress=100;const body=(xhr.responseText||"").toLowerCase();if(xhr.status>=200&&xhr.status<300){if(body.includes("добавлен во входящие"))item.status="100% · OCR завершён · нужна ручная проверка";else if(body.includes("документ сохранён")||body.includes("файл уже есть в индексе"))item.status="100% · OCR и классификация завершены";else if(body.includes("дубликат")||body.includes("уже сохранён в архиве"))item.status="100% · дубликат";else {item.progress=95;item.status="Передан серверу · результат обработки не подтверждён"}}else {item.progress=Math.min(item.progress,95);item.status="Ошибка HTTP "+xhr.status}render()};xhr.onerror=function(){item.xhr=null;if(!item.cancelled){item.status="Ошибка сети";render()}};xhr.onabort=function(){item.xhr=null};xhr.send(form)}'
            'document.getElementById("choose-files").addEventListener("click",function(){input.click()});input.addEventListener("change",function(){const selected=Array.from(input.files||[]);input.value="";selected.forEach(function(file){const item={id:++seq,file:file,status:"В очереди",progress:0,xhr:null,cancelled:false};if(!/\\.(pdf|png|jpe?g|webp|tiff?|bmp)$/i.test(file.name)){item.status="Формат не поддерживается";item.progress=0;items.push(item);render();return}if(file.size>'+str(MAX_UPLOAD_MB*1024*1024)+'){item.status="Превышен лимит размера";items.push(item);render();return}items.push(item);render();upload(item)})});'
            '})();</script>'
        )
    if fs:
        inbox_count = len(db.pending_documents(f["id"])) if f else 0
        pending_rows = db.pending_documents(f["id"])
        b.append(f'<div class="card"><h2>Нераспознанные документы</h2><p>Ожидают ручной проверки: <strong>{inbox_count}</strong></p>')
        if pending_rows:
            b.append('<div class="pending-thumbs">')
            for row in pending_rows[:4]:
                pid=int(row["id"]); name=str(row["name"]); ext=Path(name).suffix.lower()
                url=f'/families/{f["id"]}/inbox/{pid}/preview'
                if ext in {".jpg",".jpeg",".png",".webp",".bmp"}:
                    thumb=f'<img src="{url}" alt="" loading="lazy">'
                else:
                    thumb='<span class="file-thumb">'+('PDF' if ext==".pdf" else html.escape(ext.upper().lstrip(".")))+'</span>'
                b.append(f'<a class="pending-thumb" href="/families/{f["id"]}/inbox/{pid}">{thumb}<span>{html.escape(name)}</span></a>')
            if inbox_count>4: b.append(f'<a class="pending-more" href="/families/{f["id"]}/inbox">Ещё {inbox_count-4} →</a>')
            b.append('</div>')
        else:
            b.append('<p>Нет документов, ожидающих ручной проверки.</p>')
        b.append(f'<a href="/families/{f["id"]}/inbox">Открыть входящие документы</a></div>')
    if f:
        fid=f["id"]
        b.append(f'<div class="card" id="patients-section"><h2>Архив: {html.escape(f["name"])}</h2><p>Хранение документов: {"локально на VPS" if STORAGE_BACKEND == "local" else "Яндекс Диск"}</p>')
        if STORAGE_BACKEND == "yandex" and not tenancy.disk_connected(fid):
            b.append(f'<p><a href="/families/{fid}/connect-disk">Подключить Яндекс Диск</a></p>')
        b.append(f'<h2 id="patients">Пациенты</h2><p><a href="/families/{fid}/patients/new">＋ Добавить пациента</a></p>')
        ps=db.patients(fid)
        if not ps: b.append('<p>Пациентов пока нет.</p>')
        for p in ps:
            ep=html.escape(p,quote=True)
            parts=p.split()
            short_patient=(parts[1] if len(parts)>=2 else (parts[0] if parts else p))
            b.append(f'<div class="card"><strong>{html.escape(short_patient)}</strong> · документов: {db.document_count(fid,p)}<form class="row" method="get" action="/families/{fid}/patients/{ep}"><input type="search" name="q" placeholder="Поиск по документам"><button>Искать</button></form><a href="/families/{fid}/patients/{ep}">История документов</a></div>')
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
        link=f'<p><a href="/families/{fid}/documents/{int(d["id"])}">Открыть оригинал</a></p>' if STORAGE_BACKEND=="local" and d.get("remote") else ""
        b.append(f'<div class="card"><strong>{html.escape(str(title))}</strong><br>Тип: {html.escape(str(d.get("kind") or "не определено"))}<br>Дата: {html.escape(str(d.get("date") or "не указана"))}{link}<p><a href="/families/{fid}/patients/{__import__("urllib.parse",fromlist=["quote"]).quote(chosen["name"],safe="")}">История пациента</a></p><details><summary>Показать OCR-текст</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">'+html.escape((d.get("text") or "")[:4000])+'</pre></details></div>')
    return page("Поиск по архиву","".join(b))

@app.post("/families")
def create_family(name:str=Form(...),uid:int=Depends(current_user)):
    try: fid=tenancy.create_family(name,uid)
    except ValueError as e: raise HTTPException(400,str(e))
    return home_url(fid)

@app.post("/families/{fid}/patients")
def add_patient(fid:int,name:str=Form(...),birth_date:str=Form(""),aliases:str=Form(""),uid:int=Depends(current_user)):
    family(fid,uid)
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


@app.get("/families/{fid}/patients/{patient}",response_class=HTMLResponse)
def patient_page(fid:int,patient:str,q:str="",view:str="timeline",deleted:int=0,cleanup_warning:int=0,uid:int=Depends(current_user)):
    family(fid,uid)
    if patient not in db.patients(fid): raise HTTPException(404,"Пациент не найден")
    view = "tree" if view == "tree" else "timeline"
    rows=db.search(fid,patient,q,limit=1000)
    from urllib.parse import quote
    safe_patient=quote(patient,safe="")
    base=f"/families/{fid}/patients/{safe_patient}"
    b=[f'<p><a href="/?family_id={fid}">← К архиву</a></p>',f'<div class="patient-heading"><div><h2>{html.escape(patient)}</h2><p class="muted">Документов: {len(rows)}</p></div><a class="button-link" href="#patient-upload">＋ Добавить документы</a></div>']
    if deleted: b.append('<div class="notice-success" role="status">Документ удалён из архива.</div>')
    if cleanup_warning: b.append('<div class="notice-warning" role="status">Запись удалена, но временный файл не удалось окончательно очистить. Проверьте журнал приложения.</div>')
    b.append(f'<form class="card patient-search" method="get" action="{base}"><label for="patient-q">Поиск по документам пациента</label><div class="row"><input id="patient-q" type="search" name="q" value="{html.escape(q,quote=True)}" placeholder="Например: анализы, УЗИ, выписка"><input type="hidden" name="view" value="{view}"><button type="submit">Найти</button>')
    if q: b.append(f'<a class="button-link" href="{base}?view={view}">Сбросить</a>')
    b.append('</div></form>')
    if STORAGE_BACKEND == "yandex" and not tenancy.disk_connected(fid):
        b.append(f'<div class="card"><a href="/families/{fid}/connect-disk">Подключить Яндекс Диск</a></div>')
    else:
        b.append(f'<div class="card" id="patient-upload"><h3>Добавить документы</h3><form method="post" enctype="multipart/form-data" action="/families/{fid}/patients/{html.escape(patient,quote=True)}/upload"><input type="file" name="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp" required><button type="submit">Загрузить и распознать</button></form><small class="muted">PDF и изображения · до {MAX_UPLOAD_MB} МБ на файл</small></div>')
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
    if STORAGE_BACKEND != "local":
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
def upload_inbox(family_id:int=Form(...), files:list[UploadFile]=File(...), uid:int=Depends(current_user)):
    """Batch inbox upload: infer patient from OCR, never guess when matching is ambiguous."""
    f=family(family_id,uid)
    if not files:
        raise HTTPException(400,"Выберите хотя бы один файл")
    if STORAGE_BACKEND not in {"local","yandex"}:
        raise HTTPException(503,"Неизвестный backend хранения")
    token=tenancy.get_yadisk_token(family_id) if STORAGE_BACKEND=="yandex" else None
    if STORAGE_BACKEND=="yandex" and not token:
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
                        if size>MAX_UPLOAD_MB*1024*1024:
                            break
                        out.write(chunk)
                if size==0 or size>MAX_UPLOAD_MB*1024*1024:
                    results.append('<li><strong>'+html.escape(name)+'</strong>: файл пустой или превышает '+str(MAX_UPLOAD_MB)+' МБ; пропущен.</li>')
                    continue
                text=ocr_file(str(local))
                analysis=analyze_document(text)
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
                if STORAGE_BACKEND=="local":
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
                    if STORAGE_BACKEND=="local":
                        for candidate in saved_paths:
                            try: candidate.unlink()
                            except FileNotFoundError: pass
                    results.append('<li><strong>'+html.escape(name)+'</strong>: дубликат, запись не добавлена.</li>')
                    continue
                if STORAGE_BACKEND=="yandex":
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
        preview=f'<img class="preview-image" src="{preview_url}" alt="Превью документа">'
    elif ext==".pdf":
        preview=f'<p><a href="{preview_url}" target="_blank" rel="noopener">Открыть PDF в новой вкладке ↗</a></p>'
    else:
        preview=""
    body=f'<p><a href="/families/{fid}/inbox">← К входящим</a></p><h2>Классификация документа</h2><div class="card"><strong>Файл:</strong> {html.escape(d["name"])}{preview}<details><summary>Показать OCR-текст</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">{html.escape(d["text"][:12000])}</pre></details></div>'
    body+=f'<p><a href="/families/{fid}/patients/new">＋ Добавить пациента</a></p>'
    body+=f'<form method="post" action="/families/{fid}/inbox/{pending_id}/assign"><label>Пациент<br><select name="patient" required>{patient_options}</select></label><br><label>Тип документа<br><select name="kind" required>{kind_options}</select></label><br><label>Название в архиве<br><input name="title" required maxlength="180" value="{html.escape(str(d["analysis"].get("display_title") or d["analysis"].get("primary_type") or d["name"]),quote=True)}"></label><br><label>Дата документа (ДД-ММ-ГГГГ)<br><input name="date" placeholder="17-03-2025" maxlength="10"></label><p><button type="submit">Сохранить в историю пациента</button></p></form>'
    return page("Ручная классификация",body)

@app.post("/families/{fid}/inbox/{pending_id}/assign", response_class=HTMLResponse)
def assign_pending_document(fid:int,pending_id:int,patient:str=Form(...),kind:str=Form(...),title:str=Form(...),date:str=Form(""),uid:int=Depends(current_user)):
    family(fid,uid)
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
    token=tenancy.get_yadisk_token(fid) if STORAGE_BACKEND=="yandex" else None
    if STORAGE_BACKEND=="yandex" and not token: raise HTTPException(400,"Сначала подключите Яндекс Диск")
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
        if STORAGE_BACKEND=="local":
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
        if STORAGE_BACKEND=="yandex":
            hp=Path(td)/"history.txt"; hp.write_text(db.history(fid,patient),encoding="utf-8"); disk.upload_file(str(hp),folder+"/history.txt")
    return RedirectResponse(f"/families/{fid}/patients/{patient}",status_code=303)

@app.post("/families/{fid}/patients/{patient}/upload",response_class=HTMLResponse)
def upload(fid:int,patient:str,file:UploadFile=File(...),uid:int=Depends(current_user)):
    family(fid,uid)
    if patient not in db.patients(fid): raise HTTPException(404,"Пациент не найден")
    if STORAGE_BACKEND not in {"local","yandex"}: raise HTTPException(503,"Неизвестный backend хранения")
    token=tenancy.get_yadisk_token(fid) if STORAGE_BACKEND == "yandex" else None
    if STORAGE_BACKEND == "yandex" and not token: raise HTTPException(400,"Сначала подключите Яндекс Диск")
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
        saved_paths=[]
        try:
            text=ocr_file(str(local))
            analysis=analyze_document(text)
            kind=analysis["primary_type"]
            keywords=extract_keywords(text,analysis)
            date=parse_date_from_text(text)
            digest=hashlib.sha256(local.read_bytes()).hexdigest()
            ex=normalize_extension(name)
            if db.document_exists(fid,patient,digest):
                return page("Дубликат",f'<p>Этот файл уже сохранён в архиве.</p><p><a href="/families/{fid}/patients/{html.escape(patient,quote=True)}">Назад к пациенту</a></p>')
            stored=f"{Path(format_filename(patient,kind,date,ex)).stem}_{digest[:8]}.{ex}"
            ocr_stored=Path(stored).stem+".txt"
            if STORAGE_BACKEND == "local":
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
                if STORAGE_BACKEND == "local":
                    for candidate in saved_paths:
                        try: candidate.unlink()
                        except FileNotFoundError: pass
                return page("Дубликат",'<p>Файл уже есть в индексе.</p><p><a href="/">На главную</a></p>')
            if STORAGE_BACKEND == "yandex":
                with tempfile.TemporaryDirectory() as hd:
                    hp=Path(hd)/"history.txt"; hp.write_text(db.history(fid,patient),encoding="utf-8"); disk.upload_file(str(hp),folder+"/history.txt")
            status="Требуется проверить тип вручную." if analysis["review_required"] else "Тип определён автоматически; проверьте по оригиналу."
            other_types=", ".join(analysis["document_types"]) or "не определено"
            return page("Сохранено",f'<p>Документ сохранён.</p><p>Основной тип: {html.escape(kind)}.</p><p>Типы документа: {html.escape(other_types)}.</p><p>Уверенность: {html.escape(analysis["confidence"])}.</p><p>{html.escape(status)}</p><p><a href="/families/{fid}/patients/{html.escape(patient,quote=True)}">Назад к пациенту</a></p>')
        except HTTPException: raise
        except Exception as e:
            if STORAGE_BACKEND == "local":
                for candidate in saved_paths:
                    try: candidate.unlink()
                    except FileNotFoundError: pass
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