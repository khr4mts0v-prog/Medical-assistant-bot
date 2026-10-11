import asyncio, hashlib, logging, os, tempfile
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import database as db
from cloud import YaDiskClient
from ocr import ocr_file
from AIAnalise import classify_document, extract_keywords, answer_question
from utils import format_filename, parse_date_from_text, normalize_extension, safe_name

load_dotenv()
TOKEN=os.getenv("BOT_TOKEN")
HF_TOKEN=os.getenv("HF_API_TOKEN")
YADISK_TOKEN=os.getenv("YADISK_TOKEN")
ROOT=os.getenv("YADISK_ROOT_FOLDER","MedBot").strip("/")
ALLOW={x.strip() for x in os.getenv("ALLOWED_TELEGRAM_IDS","").split(",") if x.strip()}
disk=YaDiskClient(YADISK_TOKEN) if YADISK_TOKEN else None
logging.basicConfig(level=logging.INFO)
MENU=[["👤 Выбрать пациента","➕ Добавить пациента"],["📤 Загрузить документ","🔎 Найти документы"],["🧠 Анализ документов","📚 История пациента"],["ℹ️ Статус","❓ Помощь"]]

def state(c): return c.user_data.setdefault("archive",{"patient":None,"mode":None})
def allowed(u): return not ALLOW or (u.effective_user and str(u.effective_user.id) in ALLOW)
def kb(): return ReplyKeyboardMarkup(MENU,resize_keyboard=True)

async def say(u, text, markup=None):
    msg=u.effective_message
    if msg: await msg.reply_text(text,reply_markup=markup)

async def start(u,c):
    if not allowed(u): return await say(u,"Доступ запрещён.")
    await say(u,"Медицинский архив готов. Выберите пациента, затем отправляйте фото, изображения или PDF.",kb())

async def choose(u,c):
    names=db.patients()
    if not names:
        state(c)["mode"]="add"
        return await say(u,"Пациентов пока нет. Напишите имя пациента.")
    buttons=[[InlineKeyboardButton(n,callback_data="p:"+n)] for n in names]
    buttons.append([InlineKeyboardButton("➕ Добавить",callback_data="add")])
    await say(u,"Выберите пациента:",InlineKeyboardMarkup(buttons))

async def callback(u,c):
    if not allowed(u): return
    q=u.callback_query; await q.answer()
    if q.data=="add":
        state(c)["mode"]="add"; return await q.edit_message_text("Напишите имя нового пациента.")
    name=q.data[2:]
    if name not in db.patients(): return await q.edit_message_text("Пациент не найден.")
    state(c)["patient"]=name; state(c)["mode"]=None
    await q.edit_message_text("Выбран пациент: "+name)

async def text_handler(u,c):
    if not allowed(u): return await say(u,"Доступ запрещён.")
    msg=u.effective_message; text=(msg.text or "").strip(); low=text.lower(); s=state(c)
    if low in ("/start","start"): return await start(u,c)
    if low in ("/help","❓ помощь","помощь"):
        return await say(u,"1. Выберите пациента. 2. Отправьте фото/PDF. 3. Ищите документы или задавайте вопросы по архиву.\nИИ — информационный помощник, не заменяет врача.",kb())
    if low in ("👤 выбрать пациента","выбрать пациента"): return await choose(u,c)
    if low in ("➕ добавить пациента","добавить пациента"):
        s["mode"]="add"; return await say(u,"Введите имя пациента.")
    if s["mode"]=="add":
        name=" ".join(text.split())[:100]
        if not name: return await say(u,"Имя не может быть пустым.")
        db.add_patient(name); s["patient"]=name; s["mode"]=None
        return await say(u,"Пациент добавлен и выбран: "+name,kb())
    if low in ("📤 загрузить документ","загрузить документ"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        s["mode"]="upload"; return await say(u,"Теперь отправьте фотографию, изображение или PDF.")
    if low in ("🔎 найти документы","найти документы"):
        s["mode"]="search"; return await say(u,"Введите слова для поиска или «весь список».")
    if low in ("🧠 анализ документов","анализ документов","запрос к нейросети"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        s["mode"]="ai"; return await say(u,"Напишите вопрос по документам пациента.")
    if low in ("📚 история пациента","история пациента"):
        if not s["patient"]: return await say(u,"Сначала выберите пациента.")
        history=db.history(s["patient"])
        if disk:
            try:
                with tempfile.TemporaryDirectory() as td:
                    p=Path(td)/"history.txt"; p.write_text(history or "Документов пока нет",encoding="utf-8")
                    await asyncio.to_thread(disk.ensure_folder,f"{ROOT}/{safe_name(s['patient'])}")
                    await asyncio.to_thread(disk.upload_file,str(p),f"{ROOT}/{safe_name(s['patient'])}/history.txt")
            except Exception: logging.exception("History upload failed")
        return await send_long(msg,"История документов:\n"+(history or "Документов пока нет"))
    if low in ("ℹ️ статус","статус"):
        return await say(u,f"Пациент: {s['patient'] or 'не выбран'}\nДокументов в индексе: {len(db.search(s['patient'],'',1000)) if s['patient'] else '—'}\nЯндекс.Диск: {'настроен' if disk else 'нет токена'}\nИИ: {'HF-токен задан' if HF_TOKEN else 'токен не задан'}",kb())
    if s["mode"]=="search":
        rows=db.search(s["patient"],"" if low in ("весь список","все") else text)
        s["mode"]=None
        if not rows: return await say(u,"Документы не найдены.")
        out="Найдено: "+str(len(rows))
        for d in rows[:10]: out+=f"\n\n• {d['name']}\nТип: {d['kind']} | Дата: {d['date']}\nЯ.Диск: {d['remote']}"
        return await send_long(msg,out)
    if s["mode"]=="ai":
        s["mode"]=None
        ctx=db.context(s["patient"],text)
        await say(u,"Подбираю документы и готовлю ответ…")
        answer=await asyncio.to_thread(answer_question,text,s["patient"],HF_TOKEN,ctx)
        return await send_long(msg,answer)
    return await say(u,"Не понял команду. Используйте меню или /help.",kb())

async def send_long(msg,text):
    for i in range(0,len(text),3800): await msg.reply_text(text[i:i+3800])

async def process_file(u,c,path,name):
    s=state(c); patient=s.get("patient")
    if not patient: return await say(u,"Сначала выберите пациента.")
    if not disk: return await say(u,"Не настроен YADISK_TOKEN в .env.")
    await say(u,"Обрабатываю документ: "+name)
    try:
        text=await asyncio.to_thread(ocr_file,str(path))
        kind=classify_document(text); keywords=extract_keywords(text); date=parse_date_from_text(text)
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        filename=format_filename(patient,kind,date,normalize_extension(name))
        filename=f"{Path(filename).stem}_{digest[:8]}.{normalize_extension(name)}"
        folder=f"{ROOT}/{safe_name(patient)}"; docs=folder+"/docs"; ocr=folder+"/OCR"
        await asyncio.to_thread(disk.ensure_folder,docs); await asyncio.to_thread(disk.ensure_folder,ocr)
        remote=docs+"/"+filename; oremote=ocr+"/"+Path(filename).stem+".txt"
        await asyncio.to_thread(disk.upload_file,str(path),remote)
        with tempfile.TemporaryDirectory() as td:
            op=Path(td)/"ocr.txt"; op.write_text(text,encoding="utf-8")
            await asyncio.to_thread(disk.upload_file,str(op),oremote)
        added=db.add_doc(patient,filename,kind,date,remote,oremote,text,keywords,digest)
        if not added: return await say(u,"Этот файл уже есть в архиве; дубликат не добавлен в индекс.")
        # Refresh history file on Yandex Disk.
        with tempfile.TemporaryDirectory() as td:
            hp=Path(td)/"history.txt"; hp.write_text(db.history(patient),encoding="utf-8")
            await asyncio.to_thread(disk.upload_file,str(hp),folder+"/history.txt")
        await say(u,f"✅ Сохранено\nПациент: {patient}\nТип: {kind}\nДата: {date}\nКлючевые слова: {', '.join(keywords) or 'не найдены'}\nРаспознано символов: {len(text)}\nФайл: {remote}")
    except Exception as e:
        logging.exception("Document processing failed")
        await say(u,f"Ошибка обработки: {type(e).__name__}: {e}. Проверьте Tesseract, токен Яндекс.Диска и журнал.")

async def document_handler(u,c):
    if not allowed(u): return await say(u,"Доступ запрещён.")
    doc=u.effective_message.document; name=Path(doc.file_name or "document.bin").name
    if Path(name).suffix.lower() not in {".pdf",".png",".jpg",".jpeg",".webp",".tif",".tiff",".bmp"}:
        return await say(u,"Поддерживаются PDF и изображения JPG, PNG, WEBP, TIFF, BMP.")
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/name
        f=await doc.get_file(); await f.download_to_drive(custom_path=str(path))
        await process_file(u,c,path,name)

async def photo_handler(u,c):
    if not allowed(u): return await say(u,"Доступ запрещён.")
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/f"photo_{u.effective_message.message_id}.jpg"
        f=await u.effective_message.photo[-1].get_file(); await f.download_to_drive(custom_path=str(path))
        await process_file(u,c,path,path.name)

async def error_handler(u,c):
    logging.error("Telegram handler error",exc_info=c.error)

def main():
    if not TOKEN: raise RuntimeError("Set BOT_TOKEN in .env")
    if not ALLOW: logging.warning("ALLOWED_TELEGRAM_IDS пуст: ограничьте доступ к медицинским данным!")
    app=ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",text_handler))
    app.add_handler(CallbackQueryHandler(callback,pattern="^(p:|add)"))
    app.add_handler(MessageHandler(filters.PHOTO,photo_handler))
    app.add_handler(MessageHandler(filters.Document.ALL,document_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    app.add_error_handler(error_handler); app.run_polling()

if __name__=="__main__": main()
