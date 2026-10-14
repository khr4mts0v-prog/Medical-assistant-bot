"""React frontend entry point; legacy FastAPI routes remain available during migration."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parent / "frontend" / "dist"

def install_react_ui(app: FastAPI) -> None:
    assets = DIST / "assets"
    if assets.is_dir():
        app.mount("/react-assets", StaticFiles(directory=str(assets)), name="react-assets")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    def react_app():
        index = DIST / "index.html"
        if not index.is_file():
            return FileResponse(Path(__file__).resolve().parent / "frontend" / "index.html", media_type="text/html")
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
