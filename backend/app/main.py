"""The FastAPI entrypoint.

Startup does four real things: builds the schema, creates the workspace the path
guard confines writes to, drops any approval that expired while the process was
down, and asks the model providers which of them are actually answering. Nothing
here reports a service as online without having probed it.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import brain, health, voice, ws
from app.api.ws import bus_to_sockets
from app.bootstrap import ensure_monorepo_path
from app.config.settings import settings
from app.database.session import init_db
from app.events.bus import event_bus
from app.providers.registry import registry
from app.security.approvals import approval_service
from app.security.path_guard import ensure_root_exists

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("holmev.main")

DESCRIPTION = """
Local-first control plane. A request becomes an understanding, then a plan of
registered tools, then execution behind single-use parameter-bound approvals,
then verification against the filesystem or device state - and a reply that says
plainly which of those it could prove.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_monorepo_path()
    event_bus.subscribe(bus_to_sockets)
    await init_db()

    root = ensure_root_exists()
    expired = await approval_service.expire_stale()

    registry.install_defaults()
    discovered = await registry.refresh()
    serving = [f"{model.provider}:{model.name}" for model in registry.models() if model.enabled]

    app.state.started_at = time.time()
    logger.info("workspace root for all file access: %s", root)
    logger.info("voided %s approval(s) that expired while the process was down", expired)
    logger.info("model providers answering: %s", {p: len(m) for p, m in discovered.items()})
    if serving:
        logger.info("serving %s", ", ".join(serving))
    if not registry.has_any_serving_model():
        logger.warning(
            "No real model is serving, so the brain runs degraded and says so. Fix: %s",
            registry.missing_model_hint("ollama", settings.OLLAMA_DEFAULT_MODEL),
        )
    if settings.PRIVACY_LEVEL == "local_only":
        logger.info("privacy is local_only: nothing leaves this device")
    else:
        logger.warning("privacy level is '%s' - requests may leave this device", settings.PRIVACY_LEVEL)

    yield
    event_bus.unsubscribe(bus_to_sockets)
    logger.info("shutting down: pending approvals stay pending, they do not auto-run")


app = FastAPI(
    title="H.O.L.M.E.V - Multimodal Personal AI Operating System",
    version="1.0.0",
    description=DESCRIPTION,
    lifespan=lifespan,
)

_origins = settings.cors_origin_list
_wildcard = "*" in _origins
if _wildcard and settings.ENVIRONMENT.lower() in ("production", "prod"):
    raise RuntimeError(
        "CORS_ORIGINS='*' is refused in production: this API can move files, control devices and "
        "run commands, so a browser from any site must not be able to reach it. List your origins."
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    # Credentials and a wildcard origin are mutually exclusive; allowing both
    # would let any page read a user's session against this local API.
    allow_credentials=not _wildcard,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Every request gets an id, so a UI can trace one action across the event log."""

    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Process-Time-ms"] = str(int((time.perf_counter() - started) * 1000))
    return response


app.include_router(health.router)
app.include_router(brain.router)
app.include_router(voice.router)
app.include_router(ws.router)


@app.get("/")
async def root():
    return {
        "system": "H.O.L.M.E.V",
        "docs": "/docs",
        "health": "/health",
        "status": "use /health - it probes the database and the models instead of asserting",
    }
