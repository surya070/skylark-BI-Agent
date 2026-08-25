from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import BIAgent
from app.analytics import build_operations_dashboard
from app.config import get_settings
from app.monday_client import MondayClient

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

logger = logging.getLogger("skylark.bi")

settings = get_settings()
monday = MondayClient(settings)
agent = BIAgent(settings, monday)

# Simple per-IP sliding window — protects Gemini free-tier during shared demos.
CHAT_RATE_LIMIT = 10  # requests
CHAT_RATE_WINDOW_SEC = 60
_rate_hits: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = Lock()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow_chat(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        q = _rate_hits[ip]
        while q and now - q[0] > CHAT_RATE_WINDOW_SEC:
            q.popleft()
        if len(q) >= CHAT_RATE_LIMIT:
            return False
        q.append(now)
        return True


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        await monday.warm()
    except Exception as exc:  # noqa: BLE001 — a cold cache must not stop the app booting
        logger.warning("Could not prefetch monday.com boards at startup: %s", exc)
    yield


app = FastAPI(title="Skylark Drones BI Agent", version="1.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict[str, str]] = Field(default_factory=list)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health() -> JSONResponse:
    payload: dict[str, object] = {
        "model_configured": agent.configured,
        "model": agent.provider_label,
    }
    try:
        deals = await monday.deals()
        work_orders = await monday.work_orders()
        payload["monday"] = "degraded" if (deals.stale or work_orders.stale) else "connected"
        payload["deals"] = deals.freshness()
        payload["work_orders"] = work_orders.freshness()
        return JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        payload["monday"] = "unavailable"
        payload["error"] = str(exc)
        return JSONResponse(payload, status_code=503)


@app.get("/api/dashboard")
async def dashboard() -> JSONResponse:
    """Deterministic ops pulse — no LLM. Powers the glanceable dashboard above chat."""
    try:
        deals = await monday.deals()
        work_orders = await monday.work_orders()
        payload = build_operations_dashboard(deals, work_orders)
        return JSONResponse(payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Dashboard request failed")
        return JSONResponse({"error": str(exc)}, status_code=503)


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request) -> JSONResponse:
    if not _allow_chat(_client_ip(request)):
        return JSONResponse(
            {
                "reply": (
                    f"Rate limit: max {CHAT_RATE_LIMIT} questions per {CHAT_RATE_WINDOW_SEC}s "
                    "on this demo to protect the free Gemini quota. Please wait a moment."
                ),
                "tools_used": [],
                "data_freshness": {},
                "model": agent.provider_label,
            },
            status_code=429,
        )
    try:
        result = await agent.chat(body.message, body.history)
        return JSONResponse(
            {
                "reply": result.reply,
                "tools_used": result.tools_used,
                "data_freshness": result.data_freshness,
                "model": result.model or agent.provider_label,
            }
        )
    except Exception as exc:  # noqa: BLE001 — never leak a stack trace into the chat UI
        logger.exception("Chat request failed")
        return JSONResponse(
            {
                "reply": f"Something went wrong handling that question ({type(exc).__name__}). Please retry.",
                "tools_used": [],
                "data_freshness": {},
                "model": agent.provider_label,
            },
            status_code=200,
        )
