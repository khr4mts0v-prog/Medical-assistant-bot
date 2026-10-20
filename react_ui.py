"""React frontend entry point; legacy FastAPI routes remain available during migration."""
from pathlib import Path
import re

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parent / "frontend" / "dist"

# Browser navigation and hard refreshes must load the same React shell as the home page.
# React then requests the legacy HTML fragment with X-Requested-With: MedicalArchiveSPA.
_SPA_PAGE_PATHS = (
    re.compile(r"^/(?:search|assistant|settings)/?$"),
    re.compile(r"^/families/\d+/(?:patients(?:/[^/]+)?|inbox(?:/\d+)?|documents/\d+/edit)/?$"),
)

def install_react_ui(app: FastAPI) -> None:
    assets = DIST
    if assets.is_dir():
        app.mount("/react-assets", StaticFiles(directory=str(assets)), name="react-assets")

    def index_response():
        index = DIST / "index.html"
        if not index.is_file():
            index = Path(__file__).resolve().parent / "frontend" / "index.html"
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.middleware("http")
    async def serve_react_shell_for_direct_page_loads(request: Request, call_next):
        path = request.url.path
        if (
            request.method == "GET"
            and request.headers.get("x-requested-with") != "MedicalArchiveSPA"
            and any(pattern.fullmatch(path) for pattern in _SPA_PAGE_PATHS)
        ):
            return index_response()
        return await call_next(request)

    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    def react_app():
        return index_response()
