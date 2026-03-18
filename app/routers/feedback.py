"""Feedback router — submit accuracy feedback and view insights."""

import json
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.services import insights

from app.config import BASE_DIR

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.post("/feedback/{run_id}")
async def submit_feedback(
    run_id: int,
    is_accurate: bool = Form(...),
    notes: str = Form(""),
    field_corrections: str = Form("{}"),
):
    """Submit accuracy feedback for a sizing run."""
    try:
        corrections = json.loads(field_corrections) if field_corrections else None
    except json.JSONDecodeError:
        corrections = None

    insights.record_feedback(
        run_id=run_id,
        is_accurate=is_accurate,
        notes=notes or None,
        field_corrections=corrections,
    )

    return JSONResponse({"status": "ok", "message": "Feedback recorded. Thank you!"})


@router.get("/insights", response_class=HTMLResponse)
async def view_insights(request: Request):
    dd_insights = insights.get_all_insights("datadog")
    nr_insights = insights.get_all_insights("newrelic")
    return templates.TemplateResponse(
        "insights.html",
        {
            "request": request,
            "dd_insights": dd_insights,
            "nr_insights": nr_insights,
        },
    )


@router.post("/learn-csv")
async def learn_from_csvs():
    """Trigger CSV learning from screenshot directories."""
    results = insights.learn_from_csv_files()
    return JSONResponse({
        "status": "ok",
        "message": f"Processed CSVs: {results}",
        "counts": results,
    })
