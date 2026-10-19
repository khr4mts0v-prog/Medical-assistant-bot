@app.get("/manifest.webmanifest")
def pwa_manifest():
    return Response(
        '{"name":"Семейный медицинский архив","short_name":"Медархив","description":"Личный семейный архив медицинских документов","lang":"ru","start_url":"/app","scope":"/","display":"standalone","background_color":"#f2f6ff","theme_color":"#0755e8","icons":[{"src":"/apple-touch-icon.png","sizes":"180x180","type":"image/png","purpose":"any"},{"src":"/app-icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]}',
        media_type="application/manifest+json",
        headers={"Cache-Control":"no-cache"},
    )
        DEMO_CLEANUP_STARTED = True

def page(title,body,status=200):
    return HTMLResponse("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><meta name="theme-color" content="#0755e8"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="apple-mobile-web-app-title" content="Медархив"><link rel="manifest" href="/manifest.webmanifest"><link rel="icon" href="/app-icon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="/apple-touch-icon.png"><title>"""+html.escape(title)+""" · Семейный медицинский архив</title><style>
:root{color-scheme:light;--bg:#f4f8ff;--fg:#172b4d;--card:#ffffff;--line:#e2eaf5;--muted:#6b7b94;--field:#f8fbff;--accent:#3478df;--accent-strong:#245fc0;--accent-soft:#e6f0ff;--warn:#a76800;--danger:#b42318;--shadow:0 5px 22px rgba(35,76,130,.065);--radius:18px}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
.upload-fill{height:100%;width:0;background:var(--accent);transition:width .12s}
.upload-status{font-size:.9rem;color:var(--muted)}
.patient-heading{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}
.patient-actions{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;width:min(100%,520px)}
.patient-actions .button-link{min-width:0;white-space:normal;overflow-wrap:normal;word-break:normal;text-align:center;line-height:1.25;padding:10px 8px}
.patient-actions .patient-action-primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:750}
.patient-actions .patient-action-primary:hover{background:var(--accent-strong);color:#fff}
.document-card .document-main{flex:1 1 auto}
.document-meta{font-size:.9rem;margin-top:3px}
.document-finding{font-size:.94rem;margin:7px 0 2px;overflow-wrap:anywhere}
.document-source-name{margin-top:6px;font-size:.8rem;color:var(--muted)}
.document-source-name summary{cursor:pointer}
.document-source-name span{display:block;overflow-wrap:anywhere;margin-top:4px}
.button-link{display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:10px;padding:9px 13px;min-height:42px;text-decoration:none;font-weight:620;background:var(--card)}
.button-link:hover{border-color:var(--accent);color:var(--accent)}
.tabs{display:flex;gap:5px;border-bottom:1px solid var(--line);margin:20px 0 16px;overflow-x:auto}
button[type=submit]:hover{background:var(--accent-strong)}
#archive-search{flex:1 1 220px;width:auto}
hr{border:0;border-top:1px solid var(--line);margin:18px 0}
@media(max-width:600px){body{padding:17px 14px 34px}.home-actions{gap:10px}.home-action{aspect-ratio:1.05/1;min-height:120px;padding:11px;border-radius:17px;font-size:.96rem}.card{padding:16px;margin:12px 0;border-radius:15px}.home-search{padding:13px;margin-bottom:14px}.home-search .search-row{gap:7px}.home-search button{padding-inline:12px;font-size:.93rem}.patient-heading{align-items:stretch}.patient-actions{width:100%;grid-template-columns:repeat(2,minmax(0,1fr))}.patient-actions .button-link{min-height:48px;padding:9px 6px;font-size:.92rem}.document-row{align-items:flex-start;flex-direction:row}.document-card .document-main{width:100%}.document-card>.button-link{flex:0 0 auto}.tabs{gap:0}.tab{padding:10px 9px;font-size:.92rem}.timeline-date{margin-top:21px}.pending-thumbs{gap:8px}}

.app-shell{min-height:100vh}.app-sidebar{position:fixed;z-index:30;inset:0 auto 0 0;width:258px;padding:20px 14px;background:#fff;border-right:1px solid var(--line);display:flex;flex-direction:column;gap:22px;transform:translateX(-102%);transition:transform .22s ease;box-shadow:0 10px 36px rgba(35,76,130,.08)}.app-sidebar.open{transform:translateX(0)}.sidebar-brand{display:flex;gap:10px;align-items:center;padding:4px 8px 16px;font-weight:800;font-size:1.05rem}.brand-mark{display:grid;place-items:center;width:38px;height:38px;border-radius:12px;background:#e2eeff;color:#2868c7;font-size:22px}.sidebar-nav{display:grid;gap:5px}.sidebar-nav a{display:flex;align-items:center;gap:12px;padding:11px 12px;border-radius:11px;text-decoration:none;color:#526681;font-weight:650}.sidebar-nav a:hover,.sidebar-nav a.active{background:#eaf2ff;color:#245fc0}.sidebar-footer{margin-top:auto;border-top:1px solid var(--line);padding:14px 8px;color:var(--muted);font-size:.85rem}.sidebar-backdrop{display:none;position:fixed;inset:0;background:rgba(20,40,70,.25);z-index:29}.sidebar-backdrop.show{display:block}.app-topbar{display:flex;align-items:center;gap:12px;margin:0 0 22px}.menu-toggle{display:grid;place-items:center;flex:0 0 44px;width:44px;height:44px;padding:0;margin:0;background:#fff;border:1px solid var(--line);color:#2868c7;font-size:22px}.app-topbar-title{font-weight:750;font-size:1rem}.home-welcome{margin:8px 0 22px}.home-welcome h1{margin:0 0 6px}.home-welcome p{color:var(--muted);margin:0}.upload-dropzone{padding:28px 18px!important;text-align:center;background:#eef5ff!important;border:1.5px dashed #a9c9fa!important;box-shadow:none!important}.upload-dropzone h2{margin:8px 0}.patient-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.patient-card{display:flex;align-items:center;gap:12px;padding:14px;border:1px solid var(--line);border-radius:15px;background:#fff;text-decoration:none;box-shadow:var(--shadow)}.patient-avatar{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border-radius:50%;background:#e2eeff;color:#2868c7;font-weight:800}.patient-card:nth-child(4n+2) .patient-avatar{background:#dcf5e9;color:#18845d}.patient-card:nth-child(4n+3) .patient-avatar{background:#eee6ff;color:#7450bd}.patient-card:nth-child(4n+4) .patient-avatar{background:#ffecd9;color:#b66b16}.patient-card:hover{border-color:#9fc3fb;transform:translateY(-1px)}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;transition:none!important;animation:none!important}}</style></head><body><div class="app-shell"><aside class="app-sidebar" id="app-sidebar" aria-label="Основная навигация"><div class="sidebar-brand"><span class="brand-mark">✚</span><span>Medical Assistant</span></div><nav class="sidebar-nav"><a href="/" class="active">⌂　Главная</a><a href="/#quick-upload">⇧　Загрузка</a><a href="/search">⌕　Поиск</a><a href="/#patients">♧　Пациенты</a><a href="/#inbox">▤　Входящие</a><a href="/#family-settings">⚙　Настройки</a></nav><div class="sidebar-footer">Семейный медицинский архив</div></aside><div class="sidebar-backdrop" id="sidebar-backdrop"></div><main class="app-content"><header class="app-topbar"><button type="button" class="menu-toggle" id="menu-toggle" aria-label="Открыть меню" aria-expanded="false">☰</button><span class="app-topbar-title">Семейный медицинский архив</span></header><script>(function(){const s=document.getElementById("app-sidebar"),b=document.getElementById("sidebar-backdrop"),t=document.getElementById("menu-toggle");function close(){s.classList.remove("open");b.classList.remove("show");t.setAttribute("aria-expanded","false")}t.addEventListener("click",function(){const open=!s.classList.contains("open");s.classList.toggle("open",open);b.classList.toggle("show",open);t.setAttribute("aria-expanded",String(open))});b.addEventListener("click",close);document.addEventListener("keydown",e=>{if(e.key==="Escape")close()});s.querySelectorAll("a").forEach(a=>a.addEventListener("click",close))})();</script><script>if("serviceWorker" in navigator && location.protocol==="https:"){window.addEventListener("load",()=>navigator.serviceWorker.register("/sw.js").catch(()=>{}))}</script>"""+body+"""<p class="muted"><small>Тестовый MVP. Не заменяет врача.</small></p></main></div></body></html>""",status_code=status)

def format_document_count(count):
    """Return a grammatically correct Russian document count."""
    n = abs(int(count))
    last_two = n % 100
    if 11 <= last_two <= 14:
        noun = "документов"
    elif n % 10 == 1:
        noun = "документ"
    elif n % 10 in (2, 3, 4):
        noun = "документа"
    else:
        noun = "документов"
    return f"{int(count)} {noun}"


def format_document_date(value):
    """Present archive dates as DD.MM.YYYY while accepting legacy separators."""
    import re
    raw = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", raw)
    if match:
        return f"{int(match.group(1)):02d}.{int(match.group(2)):02d}.{match.group(3)}"
    return raw or "Дата не указана"


def document_card_metadata(document, analysis):
    """Extract concise, explicitly labelled clinician/clinic and conclusion hints from OCR."""
    import re
    text = str(document.get("text") or "")
    def first(patterns):
        for pattern in patterns:
            match = re.search(pattern, text, re.I | re.M)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" :;,—-")
                if value and len(value) <= 100:
                    return value
        return ""
    doctor = first([
        r"(?:врач|выполнил[аи]?|исследование пров[её]л[аи]?)\s*[:—-]\s*([^\n;]{2,100})",
        r"(?:подпись врача|врач-специалист)\s*[:—-]\s*([^\n;]{2,100})",
    ])
    clinic = first([
        r"(?:медицинск(?:ая|ой) организация|наименование клиники|клиника|медцентр|медицинский центр)\s*[:—-]\s*([^\n;]{2,100})",
    ])
    finding = ""
    a = analysis or {}
    diagnoses = a.get("diagnoses") or []
    if diagnoses:
        finding = str(diagnoses[0]).strip()
    if not finding:
        finding = first([
            r"(?:заключение|вывод|результат исследования|итог)\s*[:—-]\s*([^\n]{3,240})",
            r"(?:диагноз)\s*[:—-]\s*([^\n]{3,240})",
        ])
    finding = re.sub(r"\s+", " ", finding).strip(" :;,—-")[:180] if finding else ""
    parts = []
    if doctor: parts.append("Врач: " + doctor)
    if clinic: parts.append("Клиника: " + clinic)
    return {"doctor": doctor, "clinic": clinic, "finding": finding, "metadata": " · ".join(parts)}


def display_document_title(document, analysis):
    saved=(analysis or {}).get("display_title")
        selected_for_actions = f["id"] if f else fs[0]["id"]
        pending_for_actions = len(db.pending_documents(selected_for_actions))
        patient_count = len(db.patients(selected_for_actions))
        home_action_links = []
        if pending_for_actions:
            home_action_links.append('<a class="home-action" href="/families/' + str(selected_for_actions) + '/inbox">Входящие · на проверку (' + str(pending_for_actions) + ')</a>')
        home_action_links.append('<a class="home-action" href="#patients">Пациенты (' + str(patient_count) + ')</a>')
        b.append('<nav class="home-actions" aria-label="Основные действия">' + ''.join(home_action_links) + '</nav>')
        b.append('<section class="home-welcome"><h1>Добро пожаловать!</h1><p>Ваш семейный медицинский архив</p></section>')
        b.append('<form class="card row home-search" method="get" action="/search"><input type="hidden" name="family_id" value="' + str(selected_for_actions) + '"><label for="archive-search">⌕</label><input id="archive-search" type="search" name="q" placeholder="Найти документ, анализ, обследование…" required><button type="submit">Найти</button></form>')
    # Inbox-first workflow: files can be uploaded before opening a patient record.
            ep=html.escape(p,quote=True)
            parts=p.split()
            short_patient=(parts[1] if len(parts)>=2 else (parts[0] if parts else p))
            doc_count = db.document_count(fid,p)
            b.append(f'<a class="patient-card" href="/families/{fid}/patients/{ep}"><span class="patient-avatar">{html.escape((short_patient[:1] or "П").upper())}</span><span><strong>{html.escape(short_patient)}</strong><br><small class="muted">{format_document_count(doc_count)}</small></span></a>')
        b.append('</div>')
    b.append('<div class="card" id="family-settings"><h2>Настройки архива</h2><form method="post" action="/families"><label>Название нового семейного архива<br><input name="name" required maxlength="80"></label> <button>Создать архив</button></form></div>')
    b.append('<div class="warn"><strong>Важно:</strong> не загружайте реальные медицинские документы до настройки резервного копирования и полной проверки прав доступа.</div>')
    from urllib.parse import quote
    safe_patient=quote(patient,safe="")
    base=f"/families/{fid}/patients/{safe_patient}"
    b=[f'<p><a href="/?family_id={fid}">← К архиву</a></p>',f'<div class="patient-heading"><div><h2>{html.escape(patient)}</h2><p class="muted">{format_document_count(len(rows))}</p></div><div class="patient-actions"><a class="button-link patient-action-primary" href="#patient-assistant" data-patient-assistant="1" data-family-id="{fid}" data-patient="{html.escape(patient,quote=True)}">✦ Спросить ИИ</a><a class="button-link" href="/patient-memory?family_id={fid}&patient={safe_patient}">Память пациента</a><a class="button-link" href="/families/{fid}/patients/{safe_patient}/edit">Редактировать</a><a class="button-link" href="#patient-upload">＋ Добавить документы</a></div></div>']
    if deleted: b.append('<div class="notice-success" role="status">Документ удалён из архива.</div>')
    if cleanup_warning: b.append('<div class="notice-warning" role="status">Запись удалена, но временный файл не удалось окончательно очистить. Проверьте журнал приложения.</div>')
    b.append(f'<form class="card patient-search" method="get" action="{base}"><label for="patient-q">Поиск по документам пациента</label><div class="row"><input id="patient-q" type="search" name="q" value="{html.escape(q,quote=True)}" placeholder="Например: анализы, УЗИ, выписка"><input type="hidden" name="view" value="{view}"><button type="submit">Найти</button>')
            try: return datetime.strptime(item[0],"%d-%m-%Y")
            except Exception: return datetime.min
        for date,docs in sorted(grouped.items(),key=sort_date,reverse=True):
            b.append(f'<h3 class="timeline-date">{html.escape(format_document_date(date))}</h3>')
            for d in docs:
                analysis = d.get("analysis") or {}
                title=display_document_title(d,analysis); did=int(d["id"])
                details = document_card_metadata(d, analysis)
                meta = ('<div class="document-meta">' + html.escape(details["metadata"]) + '</div>') if details["metadata"] else ''
                finding = ('<p class="document-finding">' + html.escape(details["finding"]) + '</p>') if details["finding"] else '<p class="document-finding muted">Откройте документ, чтобы посмотреть заключение.</p>'
                b.append(f'<article class="document-row document-card"><div class="document-main"><strong>{html.escape(str(title))}</strong><div class="muted document-meta">{html.escape(str(d.get("kind") or "не определено"))} · {html.escape(format_document_date(d.get("date")))}</div>{meta}{finding}<details class="document-source-name"><summary>Имя исходного файла</summary><span>{html.escape(str(d.get("name") or ""))}</span></details></div><a class="button-link" href="/families/{fid}/documents/{did}/edit">Открыть</a></article>')
    else:
        b.append('<section class="patient-document-tree" data-patient-document-tree><div class="document-selection-toolbar"><div><strong>Выбор документов для ИИ</strong><p class="muted">По умолчанию ИИ сам ищет подходящие документы этого пациента. Включите выбор, чтобы ограничить анализ только отмеченными файлами и памятью пациента.</p></div><button type="button" class="button-link" data-toggle-document-selection aria-pressed="false">Выбрать документы</button></div><div class="document-selection-active-note" data-selection-note hidden><strong>Режим выбора включён.</strong> ИИ будет анализировать только отмеченные документы и память этого пациента.</div>')
        grouped={}
            b.append(f'<details class="tree-group" open><summary>{html.escape(kind)} <span class="muted">({len(docs)})</span></summary>')
            for d in sorted(docs,key=lambda x:str(x.get("date") or ""),reverse=True):
                title=display_document_title(d,d.get("analysis") or {}); did=int(d["id"])
                b.append(f'<div class="document-row"><label class="document-select-label"><input type="checkbox" class="document-select-checkbox" data-document-id="{did}" aria-label="Выбрать документ {html.escape(str(title),quote=True)}"><span class="document-main"><strong>{html.escape(str(title))}</strong><span class="muted">{html.escape(format_document_date(d.get("date")))}</span></span></label><a class="button-link" href="/families/{fid}/documents/{did}/edit">Открыть</a></div>')
            b.append('</details>')
        b.append('</section>')
    return page("Пациент","".join(b))