"""FastAPI app: login-protected API plus the static web UI."""
from __future__ import annotations

import asyncio
import contextlib
import logging

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from app.auth import LoginGuard, RateLimiter, verify_password
from app.coach.gemini import Coach, CoachError, gemini_transport
from app.config import Settings, load_settings
from app.garmin.client import GarminClient, GarminConnectClient, GarminError
from app.scheduler import daily_briefing_loop
from app.service import Profile, Service
from app.store import Store
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
log = logging.getLogger("benji")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class LoginBody(BaseModel):
    password: str = Field(max_length=200)


class ChatBody(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def create_app(
    settings: Settings | None = None,
    garmin: GarminClient | None = None,
    coach: Coach | None = None,
    run_scheduler: bool = False,
) -> FastAPI:
    settings = settings or load_settings()
    if len(settings.session_secret) < 32:
        raise RuntimeError("SESSION_SECRET is missing or too short. Run: python -m app.cli gen-secrets")

    store = Store(settings.db_path)
    garmin = garmin or GarminConnectClient(settings)
    coach = coach or Coach(
        settings.gemini_model, gemini_transport(settings.gemini_api_key) if settings.gemini_api_key else None
    )
    service = Service(settings, store, garmin, coach)
    guard = LoginGuard()
    chat_limit = RateLimiter(limit=20, window_s=60)
    sync_limit = RateLimiter(limit=6, window_s=300)

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI):
        task = asyncio.create_task(daily_briefing_loop(service)) if run_scheduler else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Benji Garmin Coach", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        https_only=settings.cookie_secure,
        same_site="strict",
        max_age=14 * 24 * 3600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.cookie_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    async def csrf_guard(request: Request) -> None:
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-requested-with") != "benji":
            raise HTTPException(403, "Blocked: missing request header.")

    async def require_login(request: Request) -> None:
        if not request.session.get("auth"):
            raise HTTPException(401, "Log in first.")

    api_open = [Depends(csrf_guard)]
    api_private = [Depends(csrf_guard), Depends(require_login)]

    @app.post("/api/login", dependencies=api_open)
    async def login(body: LoginBody, request: Request):
        key = client_key(request)
        left = guard.seconds_locked(key)
        if left:
            raise HTTPException(429, f"Too many wrong passwords. Try again in {left // 60 + 1} min.")
        ok = await asyncio.to_thread(verify_password, body.password, settings.app_password_hash)
        if not ok:
            guard.failure(key)
            raise HTTPException(401, "Wrong password.")
        guard.success(key)
        request.session.clear()
        request.session["auth"] = True
        return {"ok": True}

    @app.post("/api/logout", dependencies=api_open)
    async def logout(request: Request):
        request.session.clear()
        return {"ok": True}

    @app.get("/api/me")
    async def me(request: Request):
        return {"authenticated": bool(request.session.get("auth"))}

    @app.get("/api/snapshot", dependencies=api_private)
    async def snapshot():
        return await asyncio.to_thread(service.snapshot)

    @app.get("/api/trends", dependencies=api_private)
    async def trends():
        return await asyncio.to_thread(service.series)

    @app.post("/api/sync", dependencies=api_private)
    async def sync(request: Request):
        if not sync_limit.allow(client_key(request)):
            raise HTTPException(429, "Easy, you've synced a lot. Give it a few minutes.")
        try:
            return await asyncio.to_thread(service.sync)
        except GarminError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.get("/api/briefing", dependencies=api_private)
    async def briefing():
        try:
            return await asyncio.to_thread(service.briefing, False)
        except CoachError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.post("/api/briefing/refresh", dependencies=api_private)
    async def briefing_refresh(request: Request):
        if not chat_limit.allow("brief:" + client_key(request)):
            raise HTTPException(429, "Slow down a sec.")
        try:
            return await asyncio.to_thread(service.briefing, True)
        except CoachError as exc:
            raise HTTPException(502, str(exc)) from None

    @app.get("/api/chat", dependencies=api_private)
    async def chat_history():
        return {"messages": store.get_chat(60)}

    @app.post("/api/chat", dependencies=api_private)
    async def chat(body: ChatBody, request: Request):
        if not chat_limit.allow(client_key(request)):
            raise HTTPException(429, "Slow down, too many messages. Try again in a minute.")
        try:
            reply = await asyncio.to_thread(service.chat, body.message.strip())
        except CoachError as exc:
            raise HTTPException(502, str(exc)) from None
        return {"reply": reply}

    @app.delete("/api/chat", dependencies=api_private)
    async def chat_clear():
        store.clear_chat()
        return {"ok": True}

    @app.get("/api/profile", dependencies=api_private)
    async def get_profile():
        return service.get_profile()

    @app.put("/api/profile", dependencies=api_private)
    async def put_profile(profile: Profile):
        return service.save_profile(profile)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    app.state.service = service
    return app


def serve_app() -> FastAPI:
    """Production entry point: same app, with the daily briefing loop switched on."""
    return create_app(run_scheduler=True)
