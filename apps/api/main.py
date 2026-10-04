from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from . import db
from .auth import ServerSessionMiddleware, configure_oidc, router as auth_router
from .config import ROOT, settings
from .demo import router as demo_router
from .routes import router


@asynccontextmanager
async def lifespan(app):
    from packages.domain import vectorized  # Prewarm the exact array path before readiness.
    if not settings.secure and urlparse(settings.base_url).hostname not in {"localhost", "127.0.0.1"}:
        raise RuntimeError("Non-loopback APP_BASE_URL requires HTTPS")
    if (settings.oidc_issuer or settings.guest_enabled) and len(settings.session_secret) < 32:
        raise RuntimeError("Authenticated sessions require KONTROFERTA_SESSION_SECRET (32 or more characters), supplied by psst")
    db.init_db()
    configure_oidc()
    yield


app = FastAPI(title="KontrOferta", version="1.0.0", lifespan=lifespan,
              description="Evidence, deterministic offer comparison, versioned decisions. Money is stored in minor units.")
app.add_middleware(ServerSessionMiddleware)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; object-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
    if settings.secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(auth_router)
app.include_router(demo_router)
app.include_router(router)


@app.get("/api/health")
def health():
    with db.engine.connect() as conn:
        mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        conn.exec_driver_sql("SELECT 1")
    return {"status": "ok", "database": "ready", "sqliteVersion": db.sqlite3.sqlite_version,
            "journalMode": mode, "model": settings.ai_model, "oidcConfigured": bool(settings.oidc_issuer)}


web = ROOT / "apps" / "web" / "dist"
if (web / "assets").exists():
    app.mount("/assets", StaticFiles(directory=web / "assets"), name="assets")


@app.get("/materials/{name:path}", include_in_schema=False)
def materials(name: str = ""):
    allowed = {"": "materials.html", "index.html": "materials.html", "juror-guide.html": "juror-guide.html",
               "disclosures.html": "disclosures.html", "KontrOferta.pdf": "KontrOferta.pdf",
               "KontrOferta.pptx": "KontrOferta.pptx", "KontrOferta.mp4": "KontrOferta.mp4",
               "KontrOferta.srt": "KontrOferta.srt", "KontrOferta-source.zip": "KontrOferta-source.zip",
               "KontrOferta-source.sha256": "KontrOferta-source.sha256"}
    filename = allowed.get(name)
    if not filename:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    file = settings.materials_path / filename
    if not file.is_file() or not file.resolve().is_relative_to(settings.materials_path.resolve()):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return FileResponse(file, headers={"Cache-Control": "public, max-age=60"})


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    if path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    file = (web / path).resolve()
    if file.is_relative_to(web.resolve()) and file.is_file():
        return FileResponse(file)
    if (web / "index.html").exists():
        return FileResponse(web / "index.html")
    return JSONResponse({"detail": "Build apps/web first: npm run build"}, status_code=503)
