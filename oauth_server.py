"""Yandex OAuth callback server. Redirect URI must exactly match the app settings."""
import os
from urllib.parse import urlencode
import aiohttp
from aiohttp import web
import tenancy

CLIENT_ID=os.getenv("YANDEX_CLIENT_ID","").strip()
CLIENT_SECRET=os.getenv("YANDEX_CLIENT_SECRET","").strip()
REDIRECT_URI=os.getenv("YANDEX_REDIRECT_URI","").strip()
_runner=None

def configured():
    return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI.startswith("https://"))

def authorization_url(state):
    if not configured(): raise RuntimeError("Настройте YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET и HTTPS YANDEX_REDIRECT_URI")
    params={"response_type":"code","client_id":CLIENT_ID,"redirect_uri":REDIRECT_URI,
            "scope":"cloud_api:disk.read cloud_api:disk.write","state":state}
    return "https://oauth.yandex.ru/authorize?"+urlencode(params)

async def callback(request):
    error=request.query.get("error")
    if error:
        return web.Response(text="Авторизация Яндекс Диска отменена. Вернитесь в Telegram и попробуйте снова.",content_type="text/plain",status=400)
    code=request.query.get("code","")
    state=request.query.get("state","")
    if not code or not state:
        return web.Response(text="Не хватает code/state. Вернитесь в Telegram и создайте новую ссылку.",status=400)
    pending=tenancy.consume_oauth_state(state)
    if not pending:
        return web.Response(text="Ссылка истекла или уже использована. Создайте новую в Telegram.",status=400)
    if not tenancy.role_for_user(pending["family_id"],pending["telegram_id"]):
        return web.Response(text="У пользователя больше нет доступа к этому семейному архиву.",status=403)
    payload={"grant_type":"authorization_code","code":code,"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET,"redirect_uri":REDIRECT_URI}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post("https://oauth.yandex.ru/token",data=payload) as resp:
                data=await resp.json(content_type=None)
                if resp.status >= 400 or not data.get("access_token"):
                    return web.Response(text="Яндекс не выдал токен. Проверьте настройки OAuth-приложения и Redirect URI.",status=502)
        tenancy.save_yadisk_token(pending["family_id"],data["access_token"],"Подключённый Яндекс Диск")
    except Exception:
        return web.Response(text="Не удалось подключить Диск. Проверьте настройки сервера и попробуйте снова.",status=500)
    return web.Response(text="Яндекс Диск подключён. Можно вернуться в Telegram и загрузить документ.",content_type="text/plain")

async def start_server(app):
    global _runner
    if not configured():
        return
    parsed=__import__("urllib.parse",fromlist=["urlparse"]).urlparse(REDIRECT_URI)
    host=os.getenv("OAUTH_BIND_HOST","127.0.0.1")
    port=int(os.getenv("OAUTH_BIND_PORT","8080"))
    app_web=web.Application(client_max_size=1024*1024)
    app_web.router.add_get(parsed.path or "/oauth/yandex/callback",callback)
    _runner=web.AppRunner(app_web,access_log=None)
    await _runner.setup()
    site=web.TCPSite(_runner,host,port)
    await site.start()

async def stop_server(app):
    global _runner
    if _runner:
        await _runner.cleanup()
        _runner=None
