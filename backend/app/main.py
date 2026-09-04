import sys
from pathlib import Path

# Add root monorepo directory to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import time
import uuid
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config.settings import settings
from app.database.session import init_db
from app.api import health, brain, voice, ws

logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logger = logging.getLogger("holmev.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing H.O.L.M.E.V System Database and Services...")
    await init_db()
    logger.info("H.O.L.M.E.V Backend System is ONLINE.")
    yield
    logger.info("Shutting down H.O.L.M.E.V Backend System gracefully...")

app = FastAPI(
    title="H.O.L.M.E.V — Multimodal Personal AI Operating System",
    version="1.0.0",
    description="Python-First Production Multimodal AI Operating System Backend",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Correlation ID Middleware
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    start_time = time.time()
    response = await call_next(request)
    duration = int((time.time() - start_time) * 1000)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Process-Time-ms"] = str(duration)
    return response

# Include API Routers
app.include_router(health.router)
app.include_router(brain.router)
app.include_router(voice.router)
app.include_router(ws.router)

@app.get("/")
async def root():
    return {
        "system": "H.O.L.M.E.V",
        "status": "ONLINE",
        "docs": "/docs",
        "health": "/health"
    }
