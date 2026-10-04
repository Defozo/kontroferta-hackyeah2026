import hashlib
import hmac
import secrets
import time
from urllib.parse import urlparse

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, func
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from .config import settings
from .db import User, WebSession, transaction, uid

router = APIRouter(prefix="/api/auth", tags=["Identity"])
oauth = OAuth()
GUEST_ISSUER = "urn:kontroferta:public-demo"


def is_guest(user):
    return user.issuer == GUEST_ISSUER


def configure_oidc():
    if settings.oidc_issuer:
        parsed = urlparse(settings.oidc_issuer)
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "auth"):
            raise RuntimeError("OIDC issuer requires HTTPS outside loopback/local Compose")
        oauth.register(
            name="identity", client_id=settings.oidc_client_id,
            client_secret=settings.oidc_client_secret or None,
            server_metadata_url=settings.oidc_issuer + "/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256",
                           "token_endpoint_auth_method": "client_secret_basic" if settings.oidc_client_secret else "none"},
        )


def public_user(user):
    return {"id": user.id, "name": user.name, "email": user.email}


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(401, {"code": "authentication_required", "message": "Zaloguj się, aby kontynuować."})
    with transaction() as db:
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(401, "Session expired")
        return user


class ServerSessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith("/api"):
            return await call_next(request)
        # Public reads never rotate an anonymous session. Otherwise concurrent
        # /auth/me and /demo responses can leave the browser's cookie and CSRF
        # token referring to two different sessions on its first visit.
        if request.method in {"GET", "HEAD", "OPTIONS"} and (
            request.url.path == "/api/health" or request.url.path == "/api/demo" or request.url.path.startswith("/api/demo/")
        ):
            return await call_next(request)
        token = request.cookies.get("kontroferta_session")
        key = hmac.new(settings.session_secret.encode(), token.encode(), hashlib.sha256).hexdigest() if token else None
        with transaction() as db:
            row = db.get(WebSession, key) if key else None
            valid = row is not None and row.expires > time.time()
            data = dict(row.data) if valid else {}
        data.setdefault("csrf", secrets.token_urlsafe(32))
        request.scope["session"] = data
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            supplied = request.headers.get("x-csrf-token", "")
            origin = request.headers.get("origin")
            if not valid or not secrets.compare_digest(supplied, data["csrf"]) or (origin and origin != settings.base_url):
                return JSONResponse({"detail": {"code": "csrf", "message": "Odśwież stronę i ponów operację."}}, 403)
        response = await call_next(request)
        if request.scope.get("logout"):
            with transaction(write=True) as db:
                record = db.get(WebSession, key) if key else None
                if record:
                    db.delete(record)
            response.delete_cookie("kontroferta_session", path="/")
            return response
        # Rotate after authenticated callback to prevent session fixation.
        rotate = request.scope.get("rotate_session", False)
        if not valid or rotate:
            old_key = key
            token = secrets.token_urlsafe(48)
            key = hmac.new(settings.session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()
            with transaction(write=True) as db:
                old = db.get(WebSession, old_key) if old_key else None
                if old and rotate:
                    db.delete(old)
                db.add(WebSession(id=key, user_id=data.get("user_id"), data=data,
                                  expires=time.time() + settings.session_hours * 3600))
            response.set_cookie("kontroferta_session", token, max_age=settings.session_hours * 3600,
                                httponly=True, secure=settings.secure, samesite="lax", path="/")
        else:
            with transaction(write=True) as db:
                record = db.get(WebSession, key)
                if record:
                    record.data = data
                    record.user_id = data.get("user_id")
        return response


@router.get("/me")
def me(request: Request):
    user = None
    if request.session.get("user_id"):
        with transaction() as db:
            row = db.get(User, request.session["user_id"])
            if row:
                user = public_user(row)
    return {"user": user, "csrfToken": request.session["csrf"],
            "authMode": "oidc" if settings.oidc_issuer else "unconfigured",
            "guestEnabled": settings.guest_enabled,
            "localIdentity": settings.oidc_issuer.startswith("http://localhost:")}


@router.post("/guest")
def guest(request: Request):
    if not settings.guest_enabled:
        raise HTTPException(404, "Not found")
    with transaction(write=True) as db:
        existing = db.get(User, request.session.get("user_id")) if request.session.get("user_id") else None
        if existing:
            return {"user": public_user(existing)}
        active = db.scalar(select(func.count()).select_from(WebSession).join(User, User.id == WebSession.user_id)
                           .where(User.issuer == GUEST_ISSUER, WebSession.expires > time.time()))
        if active >= settings.guest_max_sessions:
            raise HTTPException(429, {"code": "guest_limit", "message": "Demo ma teraz wielu gości. Spróbuj później; zapisany przykład nadal jest dostępny."})
        user = User(id=uid(), issuer=GUEST_ISSUER, subject=uid(), name="Gość demonstracji", email="")
        db.add(user)
        request.session["user_id"] = user.id
        request.scope["rotate_session"] = True
        return {"user": public_user(user)}


@router.get("/login")
async def login(request: Request, next: str = "/#/cases"):
    if not settings.oidc_issuer:
        raise HTTPException(503, {"code": "oidc_unconfigured", "message": "Brak konfiguracji dostawcy logowania OIDC."})
    request.session["return_to"] = next if next.startswith("/#/") else "/#/cases"
    return await oauth.identity.authorize_redirect(request, settings.base_url + "/api/auth/callback", prompt="login")


@router.get("/callback")
async def callback(request: Request):
    try:
        token = await oauth.identity.authorize_access_token(request)
        info = token.get("userinfo")
        if not info or info.get("iss") != settings.oidc_issuer or not info.get("sub"):
            raise ValueError("Issuer or identity missing")
        with transaction(write=True) as db:
            row = db.scalar(select(User).where(User.issuer == info["iss"], User.subject == info["sub"]))
            if not row:
                row = User(id=uid(), issuer=info["iss"], subject=info["sub"],
                           name=info.get("name", info["sub"]), email=info.get("email", ""))
                db.add(row)
            request.session["user_id"] = row.id
        request.scope["rotate_session"] = True
        return RedirectResponse(request.session.pop("return_to", "/#/cases"))
    except Exception:
        # Provider error strings can contain credentials or codes. Do not echo them.
        raise HTTPException(400, {"code": "oidc_failed", "message": "Logowanie nie powiodło się. Rozpocznij je ponownie."}) from None


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    request.scope["logout"] = True
    return {"loggedOut": True}
