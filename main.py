import asyncio, hashlib, logging, os, tempfile, json, uuid
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import database as db
import tenancy
from cloud import YaDiskClient
from oauth_server import authorization_url, configured, start_server, stop_server
from ocr import ocr_file
from AIAnalise import analyze_document, extract_keywords, answer_question, DOCUMENT_TYPE_RULES, DOCUMENT_CATEGORIES, DOCUMENT_CATEGORY_ORDER, DOCUMENT_TAXONOMY
from utils import format_filename, parse_date_from_text, normalize_extension, safe_name
from document_metadata import extract_document_date, extract_registered_patient, infer_document_title, format_archive_filename
from upload_recovery import cleanup_unqueued_upload

TOKEN=os.getenv("BOT_TOKEN","").strip()
HF_TOKEN=os.getenv("HF_API_TOKEN","").strip()
ROOT=os.getenv("YANDEX_ROOT_FOLDER","MedArchive").strip("/")
MAX_UPLOAD_MB=max(1,int(os.getenv("MAX_UPLOAD_MB","20")))
ALLOW={x.strip() for x in os.getenv("ALLOWED_TELEGRAM_IDS","").split(",") if x.strip()}
logging.basicConfig(level=os.getenv("LOG_LEVEL","INFO"),format="%(asctime)s %(levelname)s %(message)s")
MENU=[["👪 Семьи","👤 Выбрать пациента"],["➕ Добавить пациента","📤 Загрузить документ"],["🔎 Найти документы","🧠 Анализ документов"],["📚 История пациента","☁️ Подключить Я.Диск"],["ℹ️ Статус","❓ Помощь"]]

def state(c):
    return c.user_data.setdefault("archive",{"family_id":None,"patient":None,"mode":None})

def permitted_user(u):
    return bool(u.effective_user and (not ALLOW or str(u.effective_user.id) in ALLOW))

def active_family(u,c):
    s=state(c); fid=s.get("family_id")
    if not fid or not u.effective_user: return None
    if not tenancy.role_for_user(fid,u.effective_user.id):
        s["family_id"]=None; s["patient"]=None
        return None
    return tenancy.get_family(fid)

def kb(): return ReplyKeyboardMarkup(MENU,resize_keyboard=True)

async def say(u,text,markup=None):
    if u.effective_message: await u.effective_message.reply_text(text,reply_markup=markup)

async def start(u,c):
    if not permitted_user(u): return await say(u,"Доступ к боту ограничен. Обратитесь к администратору.")
    fs=tenancy.families_for_user(u.effective_user.id)
    if not fs:
        return await say(u,"Добро пожаловать в медицинский архив. Создайте семейное пространство командой /newfamily Название или попросите администратора пригласить вас.")
    s = state(c)
    valid_ids = {int(f["id"]) for f in fs}
    if not s.get("family_id") or int(s["family_id"]) not in valid_ids:
        s["family_id"] = fs[0]["id"]
        s["patient"] = None
    family = tenancy.get_family(s["family_id"])
    if family and not db.patients(family["id"]):
        await say(u, f"Архив «{family['name']}» выбран. Для удобной автоматической сортировки сначала добавьте членов семьи: «➕ Добавить пациента». Введите короткое имя папки (например, Олег, Юля, Саша, Маша), затем варианты ФИО. Можно также сразу прислать документ — бот поможет выбрать или добавить пациента.", kb())
        return
    await say(u,"Медицинский архив. Семейный архив выбран. Чтобы сменить его, откройте «👪 Семьи». Теперь можно просто отправлять документы — пациента заранее выбирать не нужно.",kb())

async def id_command(u,c):
    if u.effective_user: await say(u,f"Ваш Telegram ID: {u.effective_user.id}\nПередавайте этот номер только администратору семейного архива для приглашения.")

async def families_command(u,c):
    if not permitted_user(u): return await say(u,"Доступ к боту ограничен.")
    fs=tenancy.families_for_user(u.effective_user.id)
    if not fs: return await say(u,"Вы пока не состоите ни в одной семье. Создайте её: /newfamily Название")
    buttons=[[InlineKeyboardButton(f"{f['name']} · {f['role']}",callback_data=f"family:{f['id']}")] for f in fs]
    await say(u,"Выберите семейный архив:",InlineKeyboardMarkup(buttons))

async def newfamily_command(u,c):
    if not permitted_user(u): return await say(u,"Доступ к боту ограничен.")
    args=" ".join(c.args or []).strip()
    if not args:
        state(c)["mode"]="newfamily"
        return await say(u,"Введите название семейного архива одним сообщением.")
    await create_family_for_user(u,c,args)

async def create_family_for_user(u,c,name):
    try: fid=tenancy.create_family(name,u.effective_user.id)
    except Exception as e: return await say(u,"Не удалось создать семью: "+str(e))
    s=state(c); s.update({"family_id":fid,"patient":None,"mode":None})
    await say(u,f"Создан архив «{name[:80]}». Подключите Яндекс Диск: /connect_disk.\n\nПеред первой загрузкой добавьте пациентов через «➕ Добавить пациента». Для каждого задайте короткое имя папки (например, Олег, Юля, Саша или Маша) и один раз укажите варианты ФИО, если хотите автоматическое распознавание. Можно и сразу загрузить документ — бот поможет настроить пациента.",kb())

async def invite_command(u,c):
    f=active_family(u,c)
    if not f: return await say(u,"Сначала выберите семейный архив: /families")
    if tenancy.role_for_user(f["id"],u.effective_user.id) not in ("owner","admin"):
        return await say(u,"Приглашать участников может владелец или администратор семьи.")
    if not c.args or not c.args[0].isdigit(): return await say(u,"Использование: /invite TELEGRAM_ID [member|admin]. Узнать свой ID: /id")
    role=c.args[1].lower() if len(c.args)>1 else "member"
    try: tenancy.add_member(f["id"],int(c.args[0]),role,u.effective_user.id)
    except Exception as e: return await say(u,"Не удалось пригласить: "+str(e))
    await say(u,f"Пользователь {c.args[0]} добавлен в «{f['name']}» с ролью {role}. Он должен открыть бота и нажать /start.")

async def connect_disk_command(u,c):
    f=active_family(u,c)
    if not f: return await say(u,"Сначала выберите семейный архив: /families")
    if tenancy.role_for_user(f["id"],u.effective_user.id) not in ("owner","admin"):
        return await say(u,"Подключить Яндекс Диск может только владелец или администратор семейного архива.")
    if not configured(): return await say(u,"OAuth пока не настроен на сервере. Нужны YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET и HTTPS YANDEX_REDIRECT_URI в .env.")
    try:
        st=tenancy.create_oauth_state(f["id"],u.effective_user.id)
        url=authorization_url(st)
    except Exception as e: return await say(u,"Не удалось подготовить авторизацию: "+str(e))
    await say(u,"Подключение Диска для семьи «"+f["name"]+"». Откройте ссылку и разрешите доступ только приложению медицинского архива:\n"+url+"\nСсылка одноразовая и действует 15 минут.")

async def callback(u,c):
    q=u.callback_query; await q.answer()
    if not permitted_user(u): return await q.edit_message_text("Доступ к боту ограничен.")
    _load_pending_queue(u,c)
    if q.data.startswith("pending_"):
        return await pending_callback(u,c,q)
    if q.data.startswith("family:") and state(c).get("pending_documents"):
        return await q.edit_message_text("Сначала завершите уточнение текущего документа или отмените ожидание командой /cancel.")
    if q.data.startswith("family:"):
        fid=int(q.data.split(":",1)[1])
        if not tenancy.role_for_user(fid,u.effective_user.id): return await q.edit_message_text("Нет доступа к этому семейному архиву.")
        f=tenancy.get_family(fid); s=state(c); s.update({"family_id":fid,"patient":None,"mode":None})
        return await q.edit_message_text(f"Выбрана семья: {f['name']}. Теперь выберите пациента.")
    f=active_family(u,c)
    if not f: return await q.edit_message_text("Сначала выберите семейный архив: /families")
    if q.data=="add_patient":
        state(c)["mode"]="add_patient"; return await q.edit_message_text("Введите имя пациента.")
    if q.data.startswith("patient:"):
        name=db.patient_by_id(f["id"],q.data[len("patient:"):])
        if not name: return await q.edit_message_text("Пациент не найден в этом семейном архиве.")
        state(c).update({"patient":name,"mode":None})
        return await q.edit_message_text("Выбран пациент: "+name)

async def choose_patient(u,c):
    f=active_family(u,c)
    if not f: return await say(u,"Сначала выберите семейный архив: /families")
    names=db.patients(f["id"])
    buttons=[[InlineKeyboardButton(n,callback_data="patient:"+str(db.patient_id(f["id"],n)))] for n in names]
    buttons.append([InlineKeyboardButton("➕ Добавить пациента",callback_data="add_patient")])
    await say(u,"Пациенты в «"+f["name"]+"»:",InlineKeyboardMarkup(buttons))

async def text_handler(u,c):
    if not permitted_user(u): return await say(u,"Доступ к боту ограничен.")
    msg=u.effective_message; text=(msg.text or "").strip(); low=text.lower(); s=state(c)
    if not text.startswith("/"):
        _load_pending_queue(u,c)
        if s.get("pending_documents"):
            if not s.get("pending_field"):
                await _advance_pending(u,c)
                return
            if await _handle_pending_text(u,c,text): return
    if low in ("/help","❓ помощь","помощь"):
        return await say(u,"Команды: /newfamily Название, /families, /invite ID [member|admin], /connect_disk, /id, /cancel, /retry_save. Выберите семейный архив и отправьте фото/PDF — пациента заранее выбирать не нужно. Если ФИО, дата заключения или тип документа не распознаны, бот уточнит их. ИИ — информационный помощник, не заменяет врача.",kb())
    if s["mode"]=="newfamily":
        return await create_family_for_user(u,c,text)
    f=active_family(u,c)
    if low in ("👪 семьи","семьи","/families"): return await families_command(u,c)
    if low in ("👤 выбрать пациента","выбрать пациента"): return await choose_patient(u,c)
    if not f:
        return await say(u,"Сначала создайте семейный архив командой /newfamily Название или выберите доступный: /families")
    if low in ("☁️ подключить я.диск","подключить я.диск","подключить диск"): return await connect_disk_command(u,c)
    if low in ("➕ добавить пациента","добавить пациента"):
        s["mode"]="add_patient"; return await say(u,"Введите короткое имя для папки пациента, например: Олег, Юля, Саша или Маша.")
    if s["mode"]=="add_patient":
        name=" ".join(text.split())[:100]
        if not name: return await say(u,"Имя не может быть пустым.")
        db.add_patient(f["id"],name)
        canonical=next((p for p in db.patients(f["id"]) if p.casefold()==name.casefold()),name)
        s.update({"patient":canonical,"new_patient_alias_name":canonical,"mode":"add_patient_aliases"})
        return await say(u,f"Пациент «{canonical}» добавлен. Чтобы распознавать его автоматически, введите полное ФИО и варианты написания через точку с запятой. Например: Иванов Иван Иванович; Иванов И.И.; Иванов И.\nПапка всё равно будет называться только «{canonical}». Если не хотите настраивать это сейчас, напишите ПРОПУСТИТЬ.")
    if s["mode"]=="add_patient_aliases":
        patient=s.get("new_patient_alias_name") or s.get("patient")
        aliases=[] if low in ("пропустить","пропустить настройку","нет","-") else [x.strip() for x in text.replace("\n",";").split(";") if x.strip()]
        try: db.update_patient_aliases(f["id"],patient,aliases)
        except Exception:
            logging.exception("Patient alias setup failed")
            return await say(u,"Не удалось сохранить варианты ФИО. Повторите список через «;» или напишите ПРОПУСТИТЬ.")
        s.update({"patient":patient,"new_patient_alias_name":None,"mode":None})
        return await say(u,f"✅ Пациент «{patient}» настроен. Папка и имя в архиве останутся короткими.",kb())
    if low in ("📤 загрузить документ","загрузить документ"):
        if not tenancy.disk_connected(f["id"]): return await say(u,"Сначала подключите Яндекс Диск этой семьи: /connect_disk")
        s["mode"]="upload"; return await say(u,"Теперь просто отправьте фото, изображение или PDF. Пациента выбирать заранее не нужно.")
    if low in ("🔎 найти документы","найти документы"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        s["mode"]="search"; return await say(u,"Введите слова для поиска или «весь список».")
    if s["mode"]=="ai_consent":
        if text.upper()=="СОГЛАСЕН":
            s["ai_consent_family"]=f["id"]; s["mode"]="ai"
            return await say(u,"Согласие сохранено для этой семьи. Напишите вопрос по документам.")
        s["mode"]=None
        return await say(u,"Анализ ИИ отменён. Документы не отправлены в ИИ.")
    if low in ("🧠 анализ документов","анализ документов"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        if not HF_TOKEN: return await say(u,"HF_API_TOKEN не настроен. Поиск и OCR работают, но ИИ пока недоступен.")
        if s.get("ai_consent_family")!=f["id"]:
            s["mode"]="ai_consent"
            return await say(u,"Важно: для ответа ИИ подходящие фрагменты OCR-текста будут отправлены в Hugging Face и выбранному провайдеру модели. Не отправляйте документы, если не согласны с обработкой третьей стороной. Чтобы разрешить анализ для этой семьи, напишите СОГЛАСЕН. Любой другой текст отменит действие.")
        s["mode"]="ai"; return await say(u,"Напишите вопрос по документам выбранного пациента.")
    if low in ("📚 история пациента","история пациента"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        history=db.history(f["id"],s["patient"])
        return await send_long(msg,"История документов семьи «"+f["name"]+"»:\n"+(history or "Документов пока нет"))
    if low in ("ℹ️ статус","статус"):
        return await say(u,f"Семья: {f['name']}\nРоль: {tenancy.role_for_user(f['id'],u.effective_user.id)}\nПациент: {s['patient'] or 'не выбран'}\nДокументов: {db.document_count(f['id'],s['patient']) if s['patient'] else '—'}\nЯндекс Диск: {'подключён' if tenancy.disk_connected(f['id']) else 'не подключён'}\nИИ: {'HF API настроен' if HF_TOKEN else 'токен не задан'}",kb())
    if s["mode"]=="search":
        rows=db.search(f["id"],s["patient"],"" if low in ("весь список","все") else text)
        s["mode"]=None
        if not rows: return await say(u,"Документы не найдены.")
        out="Найдено: "+str(len(rows))
        for d in rows[:10]: out+=f"\n\n• {d['name']}\nТип: {d['kind']} | Дата: {d['date']}\nПуть: {d['remote']}"
        return await send_long(msg,out)
    if s["mode"]=="ai":
        s["mode"]=None
        ctx=db.context(f["id"],s["patient"],text)
        if not ctx: return await say(u,"В семейном архиве нет подходящих документов.")
        await say(u,"Подбираю документы и готовлю ответ…")
        answer=await asyncio.to_thread(answer_question,text,s["patient"],HF_TOKEN,ctx)
        return await send_long(msg,answer)
    return await say(u,"Не понял команду. Используйте меню или /help.",kb())

async def send_long(msg,text):
    for i in range(0,len(text),3800): await msg.reply_text(text[i:i+3800])

PENDING_ROOT = Path(os.getenv("DB_PATH", "/app/data/archive.sqlite3")).resolve().parent / "pending_uploads"
DOCUMENT_TYPES = list(DOCUMENT_TYPE_RULES.keys())

def _pending_dir(user_id):
    root = PENDING_ROOT / str(int(user_id))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        PENDING_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        PENDING_ROOT.chmod(0o700)
        root.chmod(0o700)
    except OSError:
        pass
    return root

def _item_path(item):
    return _pending_dir(item["user_id"]) / item["stage_name"]

def _sidecar_path(item):
    return _pending_dir(item["user_id"]) / (item["id"] + ".pending")

def _persist_pending(item):
    payload = {k: v for k, v in item.items() if k != "path"}
    encrypted = tenancy.cipher().encrypt(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    target = _sidecar_path(item)
    temporary = target.with_suffix(".pending.tmp")
    temporary.write_bytes(encrypted)
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(target)
    try:
        target.chmod(0o600)
    except OSError:
        pass

def _load_pending_queue(u, c):
    s = state(c)
    if s.get("pending_loaded"):
        return
    uid = u.effective_user.id
    queue = []
    root = _pending_dir(uid)
    for sidecar in root.glob("*.pending"):
        try:
            payload = json.loads(tenancy.cipher().decrypt(sidecar.read_bytes()).decode("utf-8"))
            if int(payload.get("user_id", -1)) != int(uid):
                continue
            stage_name = payload.get("stage_name", "")
            if Path(stage_name).name != stage_name or not stage_name.endswith(".enc"):
                continue
            staged = root / stage_name
            if not staged.is_file():
                sidecar.unlink(missing_ok=True)
                continue
            payload["path"] = str(staged)
            queue.append(payload)
        except Exception as exc:
            logging.warning("Pending upload recovery skipped (%s)", type(exc).__name__)
    queue.sort(key=lambda item: item.get("created_at", ""))
    s["pending_documents"] = queue
    if queue and not s.get("pending_field"):
        s["pending_field"] = queue[0].get("pending_field")
    s["pending_loaded"] = True

def _delete_pending(item):
    for target in (_item_path(item), _sidecar_path(item)):
        try:
            target.unlink(missing_ok=True)
        except OSError:
            logging.warning("Could not remove a pending upload file")

def _set_pending_type(item, kind, user_selected=True):
    item["kind"] = (kind or "").strip()[:100] or None
    item["pending_field"] = None
    analysis = item.setdefault("analysis", {})
    if item["kind"]:
        prior = [x for x in analysis.get("document_types", []) if x and x != "не определено"]
        analysis["primary_type"] = item["kind"]
        analysis["primary_category"] = DOCUMENT_TAXONOMY.get(item["kind"], {}).get("category", "Другое / вручную указанный тип")
        analysis["taxonomy_path"] = [analysis["primary_category"], item["kind"]]
        analysis["document_types"] = list(dict.fromkeys([item["kind"]] + prior))
        content = list(analysis.get("content_tags", []))
        analysis["types"] = list(dict.fromkeys([item["kind"]] + analysis["document_types"] + content))
        analysis["review_required"] = False
        if user_selected:
            analysis["type_user_confirmed"] = True
        item["title"] = infer_document_title(item.get("text", ""), item["kind"])
    _persist_pending(item)

async def _finalize_pending(u, c, item):
    fid = int(item["family_id"])
    patient = item["patient"]
    date = item["date"]
    kind = item["kind"]
    digest = item["digest"]
    if db.document_exists(fid, patient, digest):
        return {"status": "duplicate"}
    token = tenancy.get_yadisk_token(fid)
    if not token:
        raise RuntimeError("family disk is not connected")
    title = infer_document_title(item.get("text", ""), kind)
    extension = item["extension"]
    filename = format_archive_filename(date, title, extension, digest)
    folder = f"{ROOT}/family_{fid}/{safe_name(patient)}"
    docs = folder + "/docs"
    ocr_folder = folder + "/OCR"
    remote = docs + "/" + filename
    oremote = ocr_folder + "/" + Path(filename).stem + ".txt"
    disk = YaDiskClient(token)
    await asyncio.to_thread(disk.ensure_folder, docs)
    await asyncio.to_thread(disk.ensure_folder, ocr_folder)
    original_bytes = tenancy.cipher().decrypt(Path(item["path"]).read_bytes())
    with tempfile.TemporaryDirectory() as td:
        source = Path(td) / ("original." + extension)
        source.write_bytes(original_bytes)
        await asyncio.to_thread(disk.upload_file, str(source), remote)
        ocr_source = Path(td) / "ocr.txt"
        ocr_source.write_text(item.get("text", ""), encoding="utf-8")
        await asyncio.to_thread(disk.upload_file, str(ocr_source), oremote)
    analysis = dict(item.get("analysis") or {})
    analysis["primary_type"] = kind
    analysis["primary_category"] = DOCUMENT_TAXONOMY.get(kind, {}).get("category", "Другое / вручную указанный тип")
    analysis["taxonomy_path"] = [analysis["primary_category"], kind]
    analysis["document_types"] = list(dict.fromkeys([kind] + [
        x for x in analysis.get("document_types", []) if x and x != "не определено" and x != kind
    ]))
    analysis["document_date"] = date
    analysis["filename_title"] = title
    analysis["original_filename"] = item.get("original_name", "")
    analysis["review_required"] = False
    keyword_values = list(item.get("keywords") or [])
    keyword_values.extend([kind, title])
    keywords = list(dict.fromkeys(x for x in keyword_values if x))
    added = db.add_doc(fid, patient, filename, kind, date, remote, oremote,
                       item.get("text", ""), keywords, digest, analysis=analysis)
    if not added:
        return {"status": "duplicate"}
    try:
        history = db.history(fid, patient)
        with tempfile.TemporaryDirectory() as td:
            history_path = Path(td) / "history.txt"
            history_path.write_text(history, encoding="utf-8")
            await asyncio.to_thread(disk.upload_file, str(history_path), folder + "/history.txt")
    except Exception as exc:
        logging.warning("Document saved, but patient history refresh failed (%s)", type(exc).__name__)
    return {"status": "saved", "filename": filename, "title": title, "kind": kind, "date": date}

async def _advance_pending(u, c):
    _load_pending_queue(u, c)
    s = state(c)
    queue = s.get("pending_documents", [])
    while queue:
        item = queue[0]
        fid = int(item["family_id"])
        if not tenancy.role_for_user(fid, u.effective_user.id):
            _delete_pending(item)
            queue.pop(0)
            s["pending_field"] = None
            await say(u, "Ожидающий документ удалён: у вашей учётной записи больше нет доступа к этой семье.")
            continue
        family = tenancy.get_family(fid)
        if not family:
            _delete_pending(item)
            queue.pop(0)
            continue
        label = item.get("original_name") or "загруженный документ"
        if not item.get("patient"):
            s["pending_field"] = "patient"
            item["pending_field"] = "patient"
            _persist_pending(item)
            buttons = []
            for name in db.patients(fid):
                pid = db.patient_id(fid, name)
                buttons.append([InlineKeyboardButton(name, callback_data="pending_patient:" + str(pid))])
            buttons.append([InlineKeyboardButton("➕ Добавить пациента", callback_data="pending_add_patient")])
            await say(u, f"Не удалось надёжно определить пациента для файла «{label}». Кому он принадлежит?", InlineKeyboardMarkup(buttons))
            return
        if not db.patient_aliases_configured(fid, item["patient"]):
            s["pending_field"] = "patient_aliases"
            item["pending_field"] = "patient_aliases"
            _persist_pending(item)
            await say(u, f"Чтобы дальше автоматически узнавать «{item['patient']}» по ФИО и инициалам, укажите варианты имени через «;». Это одноразовая настройка. Напишите ПРОПУСТИТЬ, если хотите продолжить без неё.")
            return
        if not item.get("date"):
            s["pending_field"] = "date"
            item["pending_field"] = "date"
            _persist_pending(item)
            await say(u, f"Не удалось определить дату заключения для файла «{label}». Введите дату документа в формате ДД.ММ.ГГГГ. Дату исследования указывать не нужно.")
            return
        if not item.get("kind"):
            category = item.get("type_category")
            if not category:
                s["pending_field"] = "type_category"
                item["pending_field"] = "type_category"
                _persist_pending(item)
                buttons = [[InlineKeyboardButton(name, callback_data=f"pending_category:{index}")]
                           for index, name in enumerate(DOCUMENT_CATEGORY_ORDER)]
                buttons.append([InlineKeyboardButton("Другое название…", callback_data="pending_type_custom")])
                await say(u, f"Не удалось уверенно определить тип документа «{label}». Сначала выберите категорию:", InlineKeyboardMarkup(buttons))
                return
            s["pending_field"] = "type"
            item["pending_field"] = "type"
            _persist_pending(item)
            buttons, row = [], []
            for index, kind in enumerate(DOCUMENT_TYPES):
                if DOCUMENT_TAXONOMY.get(kind, {}).get("category") != category:
                    continue
                row.append(InlineKeyboardButton(kind, callback_data=f"pending_type:{index}"))
                if len(row) == 2:
                    buttons.append(row)
                    row = []
            if row:
                buttons.append(row)
            buttons.append([InlineKeyboardButton("← Другую категорию", callback_data="pending_type_back")])
            buttons.append([InlineKeyboardButton("Другое название…", callback_data="pending_type_custom")])
            await say(u, f"Категория: {category}. Выберите точный тип документа:", InlineKeyboardMarkup(buttons))
            return
        try:
            result = await _finalize_pending(u, c, item)
        except Exception as exc:
            logging.exception("Pending document save failed")
            s["pending_field"] = "retry"
            item["pending_field"] = "retry"
            _persist_pending(item)
            await say(u, f"Не получилось завершить сохранение ({type(exc).__name__}). Документ пока хранится в зашифрованном ожидании. Напишите /retry_save, чтобы повторить, или /cancel, чтобы отменить ожидающие загрузки.")
            return
        _delete_pending(item)
        queue.pop(0)
        s["pending_field"] = None
        if result["status"] == "duplicate":
            await say(u, f"Этот документ уже есть в архиве пациента «{item['patient']}»; повторно не добавлял.")
        else:
            await say(u, f"✅ Сохранено\nПациент: {item['patient']}\nФайл: {result['filename']}\nТип: {result['kind']}\nДата заключения: {result['date']}")
    s["pending_field"] = None

async def _handle_pending_text(u, c, text):
    s = state(c)
    queue = s.get("pending_documents", [])
    if not queue:
        return False
    item = queue[0]
    field = s.get("pending_field") or item.get("pending_field")
    if not field:
        return False
    s["pending_field"] = field
    fid = int(item["family_id"])
    if field == "patient":
        supplied = " ".join((text or "").split()).casefold().replace("ё", "е")
        patient = next((p for p in db.patients(fid)
                        if " ".join(p.split()).casefold().replace("ё", "е") == supplied), None)
        if not patient:
            patient = extract_registered_patient(text, db.patient_records(fid))
        if not patient:
            await say(u, "Не нашёл такого пациента в архиве. Выберите пациента кнопкой ниже или нажмите «Добавить пациента».")
            names = db.patients(fid)
            buttons = [[InlineKeyboardButton(name, callback_data="pending_patient:" + str(db.patient_id(fid, name)))]
                       for name in names]
            buttons.append([InlineKeyboardButton("➕ Добавить пациента", callback_data="pending_add_patient")])
            await say(u, "Кому принадлежит документ?", InlineKeyboardMarkup(buttons))
            return True
        item["patient"] = patient
    elif field == "new_patient":
        name = " ".join((text or "").split())[:100]
        if not name:
            await say(u, "Имя не может быть пустым. Введите короткое имя для папки, например Олег, Юля, Саша или Маша.")
            return True
        db.add_patient(fid, name)
        patient = next((p for p in db.patients(fid)
                        if " ".join(p.split()).casefold().replace("ё", "е") ==
                           name.casefold().replace("ё", "е")), name)
        item["patient"] = patient
    elif field == "patient_aliases":
        aliases = [] if (text or "").strip().casefold() in ("пропустить","пропустить настройку","нет","-") else [
            value.strip() for value in (text or "").replace("\n",";").split(";") if value.strip()
        ]
        try:
            db.update_patient_aliases(fid, item["patient"], aliases)
        except Exception:
            logging.exception("Patient aliases update failed")
            await say(u, "Не получилось сохранить варианты ФИО. Повторите их через «;» или напишите ПРОПУСТИТЬ.")
            return True
    elif field == "date":
        date = extract_document_date(text)
        if not date:
            await say(u, "Не удалось разобрать дату. Введите одну дату заключения, например 12.05.2026. Не указывайте дату исследования.")
            return True
        item["date"] = date
    elif field == "type":
        raw = " ".join((text or "").split()).casefold()
        kind = next((known for known in DOCUMENT_TYPES if known.casefold() == raw), None)
        if not kind:
            await say(u, "Выберите тип документа кнопкой из списка. Для собственного названия нажмите «Другое название…».")
            return True
        _set_pending_type(item, kind)
    elif field == "type_custom":
        kind = " ".join((text or "").split())[:100]
        if not kind:
            await say(u, "Введите название типа документа.")
            return True
        _set_pending_type(item, kind)
    elif field == "retry":
        await say(u, "Документ ожидает сохранения. Напишите /retry_save для повтора или /cancel для отмены.")
        return True
    else:
        return False
    s["pending_field"] = None
    item["pending_field"] = None
    _persist_pending(item)
    await _advance_pending(u, c)
    return True

async def pending_callback(u, c, q):
    s = state(c)
    _load_pending_queue(u, c)
    queue = s.get("pending_documents", [])
    if not queue:
        return await q.edit_message_text("Этот запрос уже неактуален. Отправьте документ ещё раз.")
    item = queue[0]
    fid = int(item["family_id"])
    if not tenancy.role_for_user(fid, u.effective_user.id):
        return await q.edit_message_text("Нет доступа к семейному архиву этого документа.")
    data = q.data
    if data == "pending_add_patient":
        s["pending_field"] = "new_patient"
        item["pending_field"] = "new_patient"
        _persist_pending(item)
        return await q.edit_message_text("Введите короткое имя для папки пациента, например Олег, Юля, Саша или Маша. Полное ФИО и варианты добавим отдельным шагом.")
    if data == "pending_type_back":
        item.pop("type_category", None)
        s["pending_field"] = "type_category"
        item["pending_field"] = "type_category"
        _persist_pending(item)
        buttons = [[InlineKeyboardButton(name, callback_data=f"pending_category:{index}")]
                   for index, name in enumerate(DOCUMENT_CATEGORY_ORDER)]
        buttons.append([InlineKeyboardButton("Другое название…", callback_data="pending_type_custom")])
        return await q.edit_message_text("Выберите категорию документа:", reply_markup=InlineKeyboardMarkup(buttons))
    if data.startswith("pending_category:"):
        try:
            index = int(data.split(":", 1)[1])
            category = DOCUMENT_CATEGORY_ORDER[index]
        except (ValueError, IndexError):
            return await q.edit_message_text("Не удалось прочитать категорию. Попробуйте ещё раз.")
        item["type_category"] = category
        s["pending_field"] = "type"
        item["pending_field"] = "type"
        _persist_pending(item)
        buttons, row = [], []
        for type_index, kind in enumerate(DOCUMENT_TYPES):
            if DOCUMENT_TAXONOMY.get(kind, {}).get("category") != category:
                continue
            row.append(InlineKeyboardButton(kind, callback_data=f"pending_type:{type_index}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([InlineKeyboardButton("← Другую категорию", callback_data="pending_type_back")])
        buttons.append([InlineKeyboardButton("Другое название…", callback_data="pending_type_custom")])
        return await q.edit_message_text(f"Категория: {category}. Выберите тип:", reply_markup=InlineKeyboardMarkup(buttons))
    if data == "pending_type_custom":
        s["pending_field"] = "type_custom"
        item["pending_field"] = "type_custom"
        _persist_pending(item)
        return await q.edit_message_text("Введите краткое название типа документа.")
    if data.startswith("pending_patient:"):
        try:
            patient_id = int(data.split(":", 1)[1])
        except ValueError:
            return await q.edit_message_text("Не удалось прочитать выбор пациента. Попробуйте ещё раз.")
        patient = db.patient_by_id(fid, patient_id)
        if not patient:
            return await q.edit_message_text("Такого пациента больше нет в списке семьи.")
        item["patient"] = patient
        item["pending_field"] = None
        _persist_pending(item)
        s["pending_field"] = None
        await q.edit_message_text("Выбран пациент: " + patient)
        return await _advance_pending(u, c)
    if data.startswith("pending_type:"):
        try:
            index = int(data.split(":", 1)[1])
            kind = DOCUMENT_TYPES[index]
        except (ValueError, IndexError):
            return await q.edit_message_text("Не удалось прочитать тип документа. Выберите его ещё раз.")
        _set_pending_type(item, kind)
        s["pending_field"] = None
        await q.edit_message_text("Тип документа: " + kind)
        return await _advance_pending(u, c)
    return await q.edit_message_text("Неизвестный вариант ответа.")

async def cancel_pending_command(u, c):
    if not permitted_user(u):
        return await say(u, "Доступ к боту ограничен.")
    _load_pending_queue(u, c)
    s = state(c)
    queue = s.get("pending_documents", [])
    if not queue:
        s["pending_field"] = None
        s["mode"] = None
        return await say(u, "Нет ожидающих загрузок для отмены.")
    count = len(queue)
    for item in queue:
        _delete_pending(item)
    queue.clear()
    s["pending_field"] = None
    s["mode"] = None
    await say(u, f"Отменено ожидающих загрузок: {count}. Незавершённые файлы удалены из временного зашифрованного хранилища.")

async def retry_save_command(u, c):
    if not permitted_user(u):
        return await say(u, "Доступ к боту ограничен.")
    _load_pending_queue(u, c)
    s = state(c)
    if not s.get("pending_documents"):
        return await say(u, "Нет ожидающего документа для повторного сохранения.")
    if s.get("pending_field") not in (None, "retry"):
        return await say(u, "Сначала ответьте на текущий вопрос по документу или отмените ожидание командой /cancel.")
    s["pending_field"] = None
    s["pending_documents"][0]["pending_field"] = None
    _persist_pending(s["pending_documents"][0])
    await _advance_pending(u, c)

async def _process_file(u, c, path, name):
    s = state(c)
    family = active_family(u, c)
    if not family:
        return await say(u, "Сначала выберите семейный архив: /families. Пациента заранее выбирать не нужно.")
    fid = int(family["id"])
    if not tenancy.get_yadisk_token(fid):
        return await say(u, "Не подключён Яндекс Диск этой семьи. Используйте /connect_disk.")
    _load_pending_queue(u, c)
    if path.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
        return await say(u, f"Файл больше лимита {MAX_UPLOAD_MB} МБ.")
    await say(u, "Файл получил. Распознаю пациента, дату заключения и тип документа…")
    item_id = uuid.uuid4().hex
    root = _pending_dir(u.effective_user.id)
    stage_name = item_id + ".enc"
    staged = root / stage_name
    queued = False
    try:
        raw = path.read_bytes()
        staged.write_bytes(tenancy.cipher().encrypt(raw))
        try:
            staged.chmod(0o600)
        except OSError:
            pass
        text = await asyncio.to_thread(ocr_file, str(path))
        analysis = analyze_document(text)
        confidence = analysis.get("confidence", "low")
        kind = analysis.get("primary_type")
        if kind == "не определено" or confidence != "high":
            kind = None
        else:
            kind = kind or None
        item = {
            "id": item_id, "user_id": int(u.effective_user.id), "family_id": fid,
            "stage_name": stage_name, "original_name": Path(name or "document.bin").name[:180],
            "extension": normalize_extension(name), "digest": hashlib.sha256(raw).hexdigest(),
            "text": text, "analysis": analysis, "keywords": extract_keywords(text, analysis),
            "patient": extract_registered_patient(text, db.patient_records(fid)),
            "date": extract_document_date(text), "kind": kind, "created_at": __import__("datetime").datetime.now().isoformat(),
        }
        item["path"] = str(staged)
        if kind:
            item["title"] = infer_document_title(text, kind)
        _persist_pending(item)
        s.setdefault("pending_documents", []).append(item)
        queued = True
        if len(s["pending_documents"]) > 1 and s.get("pending_field"):
            await say(u, "Документ распознан и поставлен в очередь. Сначала уточним сведения по предыдущему файлу; повторно отправлять ничего не нужно.")
            return
        await _advance_pending(u, c)
    except Exception as exc:
        cleanup_unqueued_upload(staged, root / (item_id + ".pending"), queued)
        logging.exception("Document processing failed")
        if queued:
            await say(u, f"Документ уже помещён в зашифрованную очередь, но обработка прервалась ({type(exc).__name__}). Файл сохранён для повтора. Напишите /retry_save; повторно отправлять документ не нужно.")
        else:
            await say(u, f"Не удалось распознать документ ({type(exc).__name__}). Попробуйте отправить фото/скан ещё раз.")

_PROCESS_SEMAPHORE = asyncio.Semaphore(2)

async def process_file(u, c, path, name):
    async with _PROCESS_SEMAPHORE:
        await _process_file(u, c, path, name)

async def document_handler(u, c):
    if not permitted_user(u):
        return await say(u, "Доступ к боту ограничен.")
    doc = u.effective_message.document
    name = Path(doc.file_name or "document.bin").name
    if Path(name).suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}:
        return await say(u, "Поддерживаются PDF и изображения JPG, PNG, WEBP, TIFF, BMP.")
    if doc.file_size and doc.file_size > MAX_UPLOAD_MB * 1024 * 1024:
        return await say(u, f"Файл больше лимита {MAX_UPLOAD_MB} МБ.")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / name
        file = await doc.get_file()
        await file.download_to_drive(custom_path=str(path))
        await process_file(u, c, path, name)

async def photo_handler(u, c):
    if not permitted_user(u):
        return await say(u, "Доступ к боту ограничен.")
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / f"photo_{u.effective_message.message_id}.jpg"
        file = await u.effective_message.photo[-1].get_file()
        await file.download_to_drive(custom_path=str(path))
        if path.stat().st_size > MAX_UPLOAD_MB * 1024 * 1024:
            return await say(u, f"Файл больше лимита {MAX_UPLOAD_MB} МБ.")
        await process_file(u, c, path, path.name)


async def error_handler(u,c):
    logging.error("Telegram handler error (%s)",type(c.error).__name__)

async def post_init(app):
    await start_server(app)

async def post_shutdown(app):
    await stop_server(app)

def main():
    if not TOKEN: raise RuntimeError("Set BOT_TOKEN in .env")
    app=ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("id",id_command))
    app.add_handler(CommandHandler("help",text_handler))
    app.add_handler(CommandHandler("families",families_command))
    app.add_handler(CommandHandler("newfamily",newfamily_command))
    app.add_handler(CommandHandler("invite",invite_command))
    app.add_handler(CommandHandler("connect_disk",connect_disk_command))
    app.add_handler(CommandHandler("cancel",cancel_pending_command))
    app.add_handler(CommandHandler("retry_save",retry_save_command))
    app.add_handler(CallbackQueryHandler(callback,pattern="^(family:|patient:|add_patient$|pending_)"))
    app.add_handler(MessageHandler(filters.PHOTO,photo_handler))
    app.add_handler(MessageHandler(filters.Document.ALL,document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__=="__main__": main()