"""FastAPI application — Coralogix Sizing Tool."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.database import init_db
from app.routers import feedback, sizing
from app.services.insights import learn_from_csv_files

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

    csv_counts = learn_from_csv_files()
    if any(csv_counts.values()):
        logger.info("Learned from CSVs: %s", csv_counts)

    yield


app = FastAPI(
    title="Coralogix Sizing Tool",
    description="Convert Datadog / New Relic billing screenshots to Coralogix sizing estimates.",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(sizing.router)
app.include_router(feedback.router)
