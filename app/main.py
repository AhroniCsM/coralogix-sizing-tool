"""FastAPI application — Coralogix Sizing Tool."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR
from app.database import init_db
from app.routers import feedback, sizing
from app.services.insights import learn_from_data_files

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB, learn from any existing CSVs."""
    init_db()
    logger.info("Database initialized")

    data_counts = learn_from_data_files()
    if any(data_counts.values()):
        logger.info("Learned from data files: %s", data_counts)

    yield


app = FastAPI(
    title="Coralogix Sizing Tool",
    description="Convert Datadog / New Relic billing screenshots to Coralogix sizing estimates.",
    lifespan=lifespan,
)

# Absolute paths for static and templates
_static_dir = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

app.include_router(sizing.router)
app.include_router(feedback.router)


@app.get("/health")
async def health():
    """Health check for load balancers / container orchestrators."""
    return JSONResponse({"status": "ok"})
