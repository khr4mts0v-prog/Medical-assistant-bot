#!/usr/bin/env python3
"""Safe post-deploy smoke test for the private web archive; never prints credentials."""
import argparse
import base64
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


def read_env(path):
    values = {}
    if not path or not Path(path).is_file():
        return values
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def request(url, auth=None, timeout=10):
    headers = {"Cache-Control": "no-cache", "User-Agent": "medical-archive-release-smoke/1.0"}
    if auth:
        token = base64.b64encode((auth[0] + ":" + auth[1]).encode()).decode()
        headers["Authorization"] = "Basic " + token
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except HTTPError as exc:
        return exc.code, exc.headers, exc.read()
    except URLError as exc:
        raise RuntimeError(f"Не удалось подключиться к {url}: {exc.reason}") from exc


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    base = args.base_url.rstrip("/") + "/"
    env = read_env(args.env_file)
    username = env.get("DEMO_USERNAME", "test")
    password = env.get("DEMO_PASSWORD", "test")
    require(bool(username and password), "DEMO_USERNAME/DEMO_PASSWORD заданы пустыми: демо-вход отключён.")
    auth = (username, password)

    status, headers, body = request(urljoin(base, ""), auth)
    require(status == 200, f"Демо-вход не работает: GET / вернул HTTP {status}. Проверьте образ и DEMO_USERNAME/DEMO_PASSWORD.")
    require("Медицинский архив" in body.decode("utf-8", errors="replace"), "GET / вернул неожиданный HTML вместо страницы архива.")
    cookie = " ".join(headers.get_all("Set-Cookie") or [])
    require("medical_demo_session=" in cookie and "HttpOnly" in cookie and "Secure" in cookie,
            "Вход успешен, но демо-сессия не получила ожидаемые HttpOnly/Secure cookie.")

    status, _, app_html = request(urljoin(base, "app/"))
    require(status == 200, f"React-приложение недоступно: GET /app/ вернул HTTP {status}.")
    app_text = app_html.decode("utf-8", errors="replace")
    js_paths = re.findall(r'(?:src|href)="([^"]+\.js(?:\?[^"]*)?)"', app_text)
    css_paths = re.findall(r'href="([^"]+\.css(?:\?[^"]*)?)"', app_text)
    require(bool(js_paths), "В React shell не найден JavaScript bundle; возможна проблема сборки frontend/dist.")
    for asset in dict.fromkeys(js_paths + css_paths):
        asset_status, _, _ = request(urljoin(base, asset))
        require(asset_status == 200, f"Frontend asset недоступен (HTTP {asset_status}): {asset}")

    status, _, manifest_body = request(urljoin(base, "manifest.webmanifest"))
    require(status == 200, f"PWA manifest недоступен: HTTP {status}.")
    manifest = json.loads(manifest_body.decode("utf-8"))
    require(manifest.get("name") and manifest.get("start_url"), "PWA manifest не содержит обязательных полей.")
    status, headers, icon_body = request(urljoin(base, "apple-touch-icon.png"))
    require(status == 200 and "image/png" in headers.get("Content-Type", "") and icon_body.startswith(b"\x89PNG"),
            "Apple touch icon отсутствует или имеет неверный формат.")

    print("PASS: demo login, session cookie, React shell/assets, PWA manifest and Apple icon.")
    print("Credentials were not printed. No AI request was sent and no archive documents were modified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        raise SystemExit(1)
