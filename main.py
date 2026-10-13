import asyncio, hashlib, logging, os, tempfile
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
from AIAnalise import analyze_document, extract_keywords, answer_question
from utils import format_filename, parse_date_from_text, normalize_extension, safe_name

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
    if not state(c).get("family_id"): state(c)["family_id"]=fs[0]["id"]
    await say(u,"Медицинский архив. Выберите семейное пространство в меню «👪 Семьи». Документы разных семей изолированы.",kb())

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
    await say(u,f"Создан архив «{name[:80]}». Теперь подключите Яндекс Диск этой семьи командой /connect_disk.",kb())

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
    if low in ("/help","❓ помощь","помощь"):
        return await say(u,"Команды: /newfamily Название, /families, /invite ID [member|admin], /connect_disk, /id. Выберите семью и пациента перед загрузкой. Поддерживаются фото, изображения и PDF. ИИ — информационный помощник, не заменяет врача.",kb())
    if s["mode"]=="newfamily":
        return await create_family_for_user(u,c,text)
    f=active_family(u,c)
    if low in ("👪 семьи","семьи","/families"): return await families_command(u,c)
    if low in ("👤 выбрать пациента","выбрать пациента"): return await choose_patient(u,c)
    if not f:
        return await say(u,"Сначала создайте семейный архив командой /newfamily Название или выберите доступный: /families")
    if low in ("☁️ подключить я.диск","подключить я.диск","подключить диск"): return await connect_disk_command(u,c)
    if low in ("➕ добавить пациента","добавить пациента"):
        s["mode"]="add_patient"; return await say(u,"Введите имя пациента.")
    if s["mode"]=="add_patient":
        name=" ".join(text.split())[:100]
        if not name: return await say(u,"Имя не может быть пустым.")
        db.add_patient(f["id"],name); s.update({"patient":name,"mode":None})
        return await say(u,"Пациент добавлен и выбран: "+name,kb())
    if low in ("📤 загрузить документ","загрузить документ"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        if not tenancy.disk_connected(f["id"]): return await say(u,"Сначала подключите Яндекс Диск этой семьи: /connect_disk")
        s["mode"]="upload"; return await say(u,"Теперь отправьте фото, изображение или PDF.")
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

async def _process_file(u,c,path,name):
    s=state(c); f=active_family(u,c); patient=s.get("patient")
    if not f: return await say(u,"Сначала выберите семейный архив: /families")
    if not patient: return await say(u,"Сначала выберите пациента.")
    token=tenancy.get_yadisk_token(f["id"])
    if not token: return await say(u,"Не подключён Яндекс Диск этой семьи. Используйте /connect_disk.")
    await say(u,"Обрабатываю документ…")
    try:
        text=await asyncio.to_thread(ocr_file,str(path))
        analysis=analyze_document(text); kind=analysis["primary_type"]; keywords=extract_keywords(text,analysis); date=parse_date_from_text(text)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        ext=normalize_extension(name)
        filename=format_filename(patient,kind,date,ext)
        filename=f"{Path(filename).stem}_{digest[:8]}.{ext}"
        disk=YaDiskClient(token)
        folder=f"{ROOT}/family_{f['id']}/{safe_name(patient)}"; docs=folder+"/docs"; ocr=folder+"/OCR"
        await asyncio.to_thread(disk.ensure_folder,docs); await asyncio.to_thread(disk.ensure_folder,ocr)
        remote=docs+"/"+filename; oremote=ocr+"/"+Path(filename).stem+".txt"
        await asyncio.to_thread(disk.upload_file,str(path),remote)
        with tempfile.TemporaryDirectory() as td:
            op=Path(td)/"ocr.txt"; op.write_text(text,encoding="utf-8")
            await asyncio.to_thread(disk.upload_file,str(op),oremote)
        added=db.add_doc(f["id"],patient,filename,kind,date,remote,oremote,text,keywords,digest,analysis=analysis)
        if not added: return await say(u,"Этот файл уже есть в индексе семьи; повторно не добавлен.")
        history=db.history(f["id"],patient)
        with tempfile.TemporaryDirectory() as td:
            hp=Path(td)/"history.txt"; hp.write_text(history,encoding="utf-8")
            await asyncio.to_thread(disk.upload_file,str(hp),folder+"/history.txt")
        await say(u,f"✅ Сохранено\nСемья: {f['name']}\nПациент: {patient}\nТип: {kind}\nДата: {date}\nКлючевые слова: {', '.join(keywords) or 'не найдены'}\nРаспознано символов: {len(text)}")
    except Exception as e:
        logging.exception("Document processing failed")
        await say(u,f"Не удалось обработать документ ({type(e).__name__}). Проверьте подключение Диска и настройки OCR.")

_PROCESS_SEMAPHORE=asyncio.Semaphore(2)

async def process_file(u,c,path,name):
    async with _PROCESS_SEMAPHORE:
        await _process_file(u,c,path,name)

async def document_handler(u,c):
    if not permitted_user(u): return await say(u,"Доступ к боту ограничен.")
    doc=u.effective_message.document
    name=Path(doc.file_name or "document.bin").name
    if Path(name).suffix.lower() not in {".pdf",".png",".jpg",".jpeg",".webp",".tif",".tiff",".bmp"}:
        return await say(u,"Поддерживаются PDF и изображения JPG, PNG, WEBP, TIFF, BMP.")
    if doc.file_size and doc.file_size>MAX_UPLOAD_MB*1024*1024:
        return await say(u,f"Файл больше лимита {MAX_UPLOAD_MB} МБ.")
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/name
        file=await doc.get_file(); await file.download_to_drive(custom_path=str(path))
        await process_file(u,c,path,name)

async def photo_handler(u,c):
    if not permitted_user(u): return await say(u,"Доступ к боту ограничен.")
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/f"photo_{u.effective_message.message_id}.jpg"
        file=await u.effective_message.photo[-1].get_file(); await file.download_to_drive(custom_path=str(path))
        if path.stat().st_size>MAX_UPLOAD_MB*1024*1024: return await say(u,f"Файл больше лимита {MAX_UPLOAD_MB} МБ.")
        await process_file(u,c,path,path.name)

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
    app.add_handler(CallbackQueryHandler(callback,pattern="^(family:|patient:|add_patient$)"))
    app.add_handler(MessageHandler(filters.PHOTO,photo_handler))
    app.add_handler(MessageHandler(filters.Document.ALL,document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    app.add_error_handler(error_handler)
    app.run_polling()

if __name__=="__main__": main()
