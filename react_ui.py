"""React frontend entry point; legacy FastAPI routes remain available during migration."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from io import BytesIO
from PIL import Image, ImageDraw
from fastapi.staticfiles import StaticFiles

DIST = Path(__file__).resolve().parent / "frontend" / "dist"

def install_react_ui(app: FastAPI) -> None:
    @app.get("/apple-touch-icon.png", include_in_schema=False)
    def apple_touch_icon():
        # Generate a real PNG at request time so iOS Home Screen has a valid touch icon.
        image = Image.new("RGB", (180, 180), "#e8f1ff")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((24, 24, 156, 156), radius=30, fill="#ffffff")
        # A compact medical cross is legible at iOS icon sizes.
        draw.rounded_rectangle((77, 48, 103, 132), radius=8, fill="#2f6fce")
        draw.rounded_rectangle((48, 77, 132, 103), radius=8, fill="#2f6fce")
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return Response(
            content=buffer.getvalue(),
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    assets = DIST
    if assets.is_dir():
        app.mount("/react-assets", StaticFiles(directory=str(assets)), name="react-assets")

    @app.get("/app", include_in_schema=False)
    @app.get("/app/", include_in_schema=False)
    def react_app():
        index = DIST / "index.html"
        if not index.is_file():
            return FileResponse(Path(__file__).resolve().parent / "frontend" / "index.html", media_type="text/html")
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
