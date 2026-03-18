"""Admin router — dashboard, audit log, user management."""

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR
from app.database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def is_admin(email: str) -> bool:
    """Check if a user email is in the admin_users table."""
    with get_db() as db:
        row = db.execute(
            "SELECT 1 FROM admin_users WHERE email = ?", (email,)
        ).fetchone()
    return row is not None


def _require_admin(request: Request) -> RedirectResponse | None:
    """Return redirect if user is not an admin."""
    user = request.session.get("user")
    if not user or not is_admin(user["email"]):
        return RedirectResponse("/", status_code=303)
    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Admin dashboard with stats and recent activity."""
    redirect = _require_admin(request)
    if redirect:
        return redirect

    with get_db() as db:
        # Total runs
        total_runs = db.execute("SELECT COUNT(*) as c FROM sizing_runs").fetchone()["c"]

        # Unique users
        unique_users = db.execute(
            "SELECT COUNT(DISTINCT user_email) as c FROM sizing_runs WHERE user_email IS NOT NULL"
        ).fetchone()["c"]

        # Runs by provider
        provider_stats = db.execute(
            "SELECT provider, COUNT(*) as c FROM sizing_runs GROUP BY provider"
        ).fetchall()
        provider_counts = {row["provider"]: row["c"] for row in provider_stats}

        # Feedback stats
        total_feedback = db.execute("SELECT COUNT(*) as c FROM feedback").fetchone()["c"]
        accurate_count = db.execute(
            "SELECT COUNT(*) as c FROM feedback WHERE is_accurate = 1"
        ).fetchone()["c"]
        inaccurate_count = total_feedback - accurate_count

        # Runs today
        runs_today = db.execute(
            "SELECT COUNT(*) as c FROM sizing_runs WHERE DATE(created_at) = DATE('now')"
        ).fetchone()["c"]

        # Runs this week
        runs_week = db.execute(
            "SELECT COUNT(*) as c FROM sizing_runs WHERE created_at >= DATE('now', '-7 days')"
        ).fetchone()["c"]

        # Recent activity (last 20 runs with feedback)
        recent_runs = db.execute(
            """SELECT s.id, s.user_email, s.provider, s.created_at, s.status,
                      f.is_accurate, f.notes as feedback_notes, f.created_at as feedback_at
               FROM sizing_runs s
               LEFT JOIN feedback f ON f.run_id = s.id
               ORDER BY s.created_at DESC
               LIMIT 20"""
        ).fetchall()
        recent = [dict(r) for r in recent_runs]

        # Top users by run count
        top_users = db.execute(
            """SELECT user_email, COUNT(*) as run_count,
                      MAX(created_at) as last_active
               FROM sizing_runs
               WHERE user_email IS NOT NULL
               GROUP BY user_email
               ORDER BY run_count DESC
               LIMIT 10"""
        ).fetchall()
        top = [dict(r) for r in top_users]

        # Admin list
        admins = db.execute(
            "SELECT email, created_at FROM admin_users ORDER BY created_at"
        ).fetchall()
        admin_list = [dict(r) for r in admins]

    stats = {
        "total_runs": total_runs,
        "unique_users": unique_users,
        "runs_today": runs_today,
        "runs_week": runs_week,
        "dd_runs": provider_counts.get("datadog", 0),
        "nr_runs": provider_counts.get("newrelic", 0),
        "total_feedback": total_feedback,
        "accurate_count": accurate_count,
        "inaccurate_count": inaccurate_count,
        "accuracy_pct": round(100 * accurate_count / total_feedback, 1) if total_feedback else 0,
    }

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "stats": stats,
            "recent_runs": recent,
            "top_users": top,
            "admin_list": admin_list,
        },
    )


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

@router.post("/users/add-admin")
async def add_admin(request: Request):
    """Add a user as admin."""
    redirect = _require_admin(request)
    if redirect:
        return redirect

    form = await request.form()
    email = str(form.get("email", "")).strip().lower()

    if not email or not email.endswith("@coralogix.com"):
        return RedirectResponse("/admin?error=Invalid email", status_code=303)

    with get_db() as db:
        db.execute("INSERT OR IGNORE INTO admin_users (email) VALUES (?)", (email,))

    logger.info("Admin added: %s (by %s)", email, request.session["user"]["email"])
    return RedirectResponse("/admin?success=Admin added", status_code=303)


@router.post("/users/remove-admin")
async def remove_admin(request: Request):
    """Remove admin access from a user."""
    redirect = _require_admin(request)
    if redirect:
        return redirect

    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    current_user = request.session["user"]["email"]

    # Can't remove yourself
    if email == current_user:
        return RedirectResponse("/admin?error=Cannot remove yourself", status_code=303)

    with get_db() as db:
        db.execute("DELETE FROM admin_users WHERE email = ?", (email,))

    logger.info("Admin removed: %s (by %s)", email, current_user)
    return RedirectResponse("/admin?success=Admin removed", status_code=303)
