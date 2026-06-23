"""FastAPI entrypoint."""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.facebook import router as facebook_router
from app.api.health import router as health_router
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

# დროებითი ღია CORS — production-ში შეიზღუდება frontend-ის დომენით
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(shops_router)
app.include_router(products_router)
app.include_router(chat_router)
app.include_router(webhook_router)
app.include_router(facebook_router)


@app.get("/")
def root():
    return {"name": "shop-ai-bot", "version": "0.1.0", "env": settings.app_env}


# გამყიდველის პანელის მომსახურება იმავე backend-იდან — ngrok-ით გასაზიარებლად.
# პანელი ხელმისაწვდომია: <backend-url>/panel/
_FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/panel", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="panel")
