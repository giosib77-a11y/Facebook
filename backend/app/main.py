"""FastAPI entrypoint."""
import logging
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
    """ბრაუზერმა პანელის ფაილები რომ არ დააქეშოს (ცვლილებები მაშინვე ჩანდეს)."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp


_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/panel", _NoCacheStatic(directory=str(_FRONTEND_DIR), html=True), name="panel")
