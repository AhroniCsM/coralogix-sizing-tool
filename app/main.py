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


def _seed_data_dir() -> None:
    """Copy bundled reference data to the persistent volume on first run."""
    from app.config import settings
    import shutil

    bundled = BASE_DIR / "seed_data"
    if not bundled.exists():
        return

    for provider in ("datadog", "newrelic"):
        src = bundled / provider
        dst = settings.screenshots_dir / provider
        if not src.exists():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            target = dst / f.name
            if not target.exists():
                shutil.copy2(f, target)
                logger.info("Seeded %s → %s", f.name, provider)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: ensure dirs, init DB, seed data, learn from data files."""
    from app.config import settings

    # Ensure data directories exist (important for fresh deploys)
    settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
    (settings.screenshots_dir / "datadog").mkdir(exist_ok=True)
    (settings.screenshots_dir / "newrelic").mkdir(exist_ok=True)

    # Seed reference spreadsheets from bundled data (first deploy only)
    _seed_data_dir()

    init_db()
    logger.info("Database initialized (BASE_DIR=%s)", BASE_DIR)

    try:
        data_counts = learn_from_data_files()
        if any(data_counts.values()):
            logger.info("Learned from data files: %s", data_counts)
    except Exception as e:
        logger.warning("Data file learning failed (non-fatal): %s", e)

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
