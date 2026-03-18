"""FastAPI application — Coralogix Sizing Tool."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.config import BASE_DIR, settings
from app.database import init_db
from app.routers import admin, auth, feedback, sizing
from app.routers.admin import is_admin as check_admin
from app.services.insights import learn_from_data_files

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# Paths that don't require authentication
PUBLIC_PATHS = {"/login", "/auth/google", "/auth/callback", "/health", "/logout"}
PUBLIC_PREFIXES = ("/static/",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated users to /login for protected routes."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Check if OAuth is configured — if not, skip auth (local dev)
        if not settings.google_client_id:
            return await call_next(request)

        # Check session
        user = request.session.get("user")
        if not user:
            return RedirectResponse("/login", status_code=303)

        # Set admin flag for templates (accessible via request.state)
        request.state.is_admin = check_admin(user["email"])

        return await call_next(request)


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

# Middleware order matters: add_middleware uses LIFO, so SessionMiddleware (added last)
# wraps outermost → it runs first, sets up session → then AuthMiddleware can access it.
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    same_site="lax",
    https_only=True,
)

# Absolute paths for static and templates
_static_dir = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

app.include_router(auth.router)
app.include_router(sizing.router)
app.include_router(feedback.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    """Health check for load balancers / container orchestrators."""
    return JSONResponse({"status": "ok"})
