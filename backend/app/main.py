"""FastAPI entrypoint."""
import hmac
import json
import logging
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.facebook import router as facebook_router
from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.products import router as products_router
from app.api.shops import router as shops_router
from app.api.webhook import router as webhook_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="ქართული მაღაზიების AI ბოტი — API",
    description="Multi-tenant SaaS: Facebook Messenger AI ბოტი ქართული მაღაზიებისთვის",
    version="0.1.0",
)

logger = logging.getLogger("app")

# ── მოთხოვნის ზომის ლიმიტი (FA-07/FA-08) ──
# უზარმაზარი body მეხსიერებაში რომ არ ჩაიტვირთოს — 413 ვაბრუნებთ, სანამ handler-ამდე მივა.
_MiB = 1024 * 1024
_DEFAULT_BODY_LIMIT = 256 * 1024
_KNOWLEDGE_PATH = re.compile(r"^/shops/[^/]+/knowledge$")
_TOO_LARGE_BODY = json.dumps({"detail": "მოთხოვნა ძალიან დიდია"}, ensure_ascii=False).encode()


def _body_limit(path: str) -> int:
    if path == "/products/upload-image":
        return 9 * _MiB
    if path.startswith("/products/import"):
        return 6 * _MiB
    if _KNOWLEDGE_PATH.match(path):
        return 11 * _MiB
    if path == "/webhook":
        return 1 * _MiB
    return _DEFAULT_BODY_LIMIT


async def _send_too_large(send) -> None:
    await send({
        "type": "http.response.start",
        "status": 413,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_TOO_LARGE_BODY)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": _TOO_LARGE_BODY})


class BodySizeLimitMiddleware:
    """Pure ASGI: POST/PUT/PATCH body-ს ზღუდავს — ჯერ Content-Length-ით, მერე ბაიტების თვლით
    (chunked მოთხოვნას Content-Length არ აქვს)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return
        limit = _body_limit(scope["path"])

        for name, value in scope["headers"]:
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    break  # არავალიდური — ქვემოთ ბაიტების თვლა მაინც დაიცავს
                if declared > limit:
                    await _send_too_large(send)
                    return
                break

        received = 0
        rejected = False
        response_started = False

        async def limited_receive():
            nonlocal received, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # ეს chunk app-ს აღარ გადაეცემა; app-ისთვის კლიენტი „გაითიშა"
                    rejected = True
                    if not response_started:
                        await _send_too_large(send)
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message):
            nonlocal response_started
            if rejected:
                return  # 413 უკვე გაიგზავნა — app-ის პასუხს ვყლაპავთ
            response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except Exception:
            # 413-ის შემდეგ app-ის შეცდომა (მაგ. ClientDisconnect) მოსალოდნელი შედეგია
            if not rejected:
                raise


# ── Origin lock (FA-03) ──
# Render-ის origin პირდაპირაც ხელმისაწვდომია, ანუ CF-Connecting-IP ყალბდება. production-ში,
# ORIGIN_SECRET-ის არსებობისას, მხოლოდ Cloudflare-ის გავლით (საიდუმლო header-ით) მოსულს ვუშვებთ.
_ORIGIN_LOCK_EXEMPT = "/health"  # Render-ის health check origin-ს პირდაპირ ურტყამს
_FORBIDDEN_BODY = json.dumps({"detail": "Forbidden"}).encode()

if settings.is_production and not settings.origin_secret:
    logger.warning("ORIGIN_SECRET not set — origin lock disabled; CF-Connecting-IP is spoofable")


class OriginLockMiddleware:
    """Pure ASGI: საიდუმლო header-ის გარეშე HTTP მოთხოვნა → 403, app არ გამოიძახება."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        secret = settings.origin_secret
        if (
            scope["type"] != "http"
            or not secret
            or not settings.is_production
            or scope["path"] == _ORIGIN_LOCK_EXEMPT
        ):
            await self.app(scope, receive, send)
            return

        wanted = settings.origin_secret_header.strip().lower().encode("latin-1")
        provided = b""
        for name, value in scope["headers"]:
            if name == wanted:
                provided = value
                break
        if provided and hmac.compare_digest(provided, secret.encode()):
            await self.app(scope, receive, send)
            return

        await send({
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(_FORBIDDEN_BODY)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": _FORBIDDEN_BODY})


# ყველაზე შიდა user middleware — 413 პასუხსაც CORS და security ჰედერები მოხვდება.
app.add_middleware(BodySizeLimitMiddleware)

# CORS — origin-ები .env-ის CORS_ORIGINS-იდან ("*" = ყველა, მხოლოდ dev-ისთვის).
# production-ში დააყენე CORS_ORIGINS="https://shendomen.ge".
_origins = settings.cors_origins_list
if settings.is_production and _origins == ["*"]:
    logger.warning(
        "CORS: production-ში wildcard '*' გამოიყენება — დააყენე CORS_ORIGINS "
        "კონკრეტულ დომენზე (მაგ. https://chatassist.ge) .env-ში."
    )
# credentials + "*" ერთად ბრაუზერში არ მუშაობს — კონკრეტულ დომენებზე ჩავრთავთ.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """უსაფრთხოების ჰედერები ყველა პასუხზე."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# ყველაზე გარე user middleware (ბოლოს დამატებული) — origin-ის შემოწმება ყველაფერზე ადრე.
app.add_middleware(OriginLockMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """მოულოდნელი შეცდომა — production-ში ზოგადი პასუხი (stack trace არ ჟონავს)."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    if settings.is_production:
        return JSONResponse(status_code=500, content={"detail": "სერვერის შიდა შეცდომა"})
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

app.include_router(health_router)
app.include_router(shops_router)
app.include_router(products_router)
app.include_router(chat_router)
app.include_router(webhook_router)
app.include_router(facebook_router)
app.include_router(orders_router)
app.include_router(admin_router)


@app.get("/")
def root():
    # მთავარი გვერდი = მარკეტინგული landing (პანელი რჩება /panel/-ზე)
    return RedirectResponse(url="/panel/landing.html")


@app.get("/status")
def status():
    return {"name": "chatassist", "version": "0.1.0", "env": settings.app_env}


# გამყიდველის პანელის მომსახურება იმავე backend-იდან — ngrok-ით გასაზიარებლად.
# პანელი ხელმისაწვდომია: <backend-url>/panel/
class _NoCacheStatic(StaticFiles):
    """ბრაუზერმა პანელის ფაილები რომ არ დააქეშოს (ცვლილებები მაშინვე ჩანდეს).

    extra_dirs — დამატებითი საქაღალდეები, სადაც ფაილი უნდა მოიძებნოს, თუ მთავარში არაა.
    საჭიროა fallback-რეჟიმისთვის: build-ის გარეშე `config.js`/`favicon.svg`
    `frontend/public/`-შია, HTML კი მათ ძირიდან ითხოვს.
    """

    def __init__(self, *args, extra_dirs=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.all_directories = list(self.all_directories) + [Path(d) for d in extra_dirs]

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        # Vite-ის ჰეშირებული ასეტები (assets/index-AbC123.js) — სახელი შიგთავსზეა
        # დამოკიდებული, ანუ ცვლილებისას სახელიც იცვლება. ამიტომ სამუდამოდ ქეშირებადია.
        # ⚠️ HTML და config.js აქ არ ხვდება — ისინი no-store რჩება, რომ ცვლილება
        # (მაგ. ახალი bundle-ის სახელი ან შეცვლილი კონფიგი) მაშინვე ჩანდეს.
        if path.replace("\\", "/").startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp


_FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend"
_FRONTEND_DIST = _FRONTEND_SRC / "dist"
# React-ის build-ის გამოსავალი (frontend/dist), თუ არსებობს; თუ არა — ძველი frontend/.
# ეს fallback უსაფრთხოების ბადეა: build რომ ვერ აეწყოს, საიტი მაინც მუშაობს.
_FRONTEND_DIR = _FRONTEND_DIST if (_FRONTEND_DIST / "index.html").exists() else _FRONTEND_SRC
if _FRONTEND_DIR.exists():
    # fallback-რეჟიმში (dist არ არსებობს) public/-იც უნდა ჩანდეს ძირად, თორემ
    # config.js ვერ ჩაიტვირთება და პანელი მკვდარი იქნება.
    _extra = [] if _FRONTEND_DIR == _FRONTEND_DIST else [_FRONTEND_SRC / "public"]
    _extra = [d for d in _extra if d.exists()]
    app.mount(
        "/panel",
        _NoCacheStatic(directory=str(_FRONTEND_DIR), html=True, extra_dirs=_extra),
        name="panel",
    )
