"""Sizing router — upload screenshots, extract values, calculate results."""

import json
import logging
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import get_db
from app.models import DatadogExtraction, NewRelicExtraction
from app.services import datadog, extractor, insights, newrelic

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/upload")
async def upload(
    request: Request,
    provider: str = Form(...),
    screenshots: list[UploadFile] = File(...),
):
    """Save screenshots, run Claude Vision extraction, show review form."""
    # Validate provider
    if provider not in ("datadog", "newrelic"):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Invalid provider. Choose Datadog or New Relic."},
            status_code=400,
        )

    # Validate files
    if not screenshots or all(f.filename == "" for f in screenshots):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Please upload at least one screenshot."},
            status_code=400,
        )

    # Save screenshots
    provider_dir = settings.screenshots_dir / provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for upload_file in screenshots:
        if not upload_file.filename:
            continue
        suffix = Path(upload_file.filename).suffix.lower()
        if suffix not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            continue
        unique_name = f"{uuid.uuid4().hex[:8]}_{upload_file.filename}"
        dest = provider_dir / unique_name
        with open(dest, "wb") as f:
            shutil.copyfileobj(upload_file.file, f)
        saved_paths.append(dest)

    if not saved_paths:
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "No valid image files uploaded."},
            status_code=400,
        )

    # Get hints from past feedback
    hints = insights.get_hints(provider)

    # Extract values using Claude Vision
    try:
        if provider == "datadog":
            extraction = await extractor.extract_datadog(saved_paths, hints)
        else:
            extraction = await extractor.extract_newrelic(saved_paths, hints)
    except Exception as e:
        logger.exception("Extraction failed")
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"Extraction failed: {e}"},
            status_code=500,
        )

    # Store run in DB
    extraction_dict = extraction.model_dump()
    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO sizing_runs (provider, raw_extraction, screenshot_paths, missing_fields)
               VALUES (?, ?, ?, ?)""",
            (
                provider,
                json.dumps(extraction_dict),
                json.dumps([str(p) for p in saved_paths]),
                json.dumps(extraction_dict.get("missing_fields", [])),
            ),
        )
        run_id = cursor.lastrowid

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "run_id": run_id,
            "provider": provider,
            "extraction": extraction_dict,
            "step": "review",
            "results": None,
        },
    )


@router.post("/calculate")
async def calculate(request: Request):
    """Accept corrected values, run formulas, show results."""
    form = await request.form()
    run_id = int(form.get("run_id", 0))
    provider = str(form.get("provider", ""))

    if not run_id or provider not in ("datadog", "newrelic"):
        return RedirectResponse("/", status_code=303)

    # Build corrected extraction from form values
    corrected: dict = {}
    for key, value in form.items():
        if key in ("run_id", "provider"):
            continue
        if value == "" or value is None:
            corrected[key] = None
        elif key.endswith("_is_hourly"):
            corrected[key] = value == "true"
        else:
            try:
                corrected[key] = float(value)
            except (ValueError, TypeError):
                corrected[key] = value

    # Calculate sizing
    try:
        if provider == "datadog":
            ext = DatadogExtraction(**corrected)
            result = datadog.calculate(ext)
        else:
            ext = NewRelicExtraction(**corrected)
            result = newrelic.calculate(ext)
    except Exception as e:
        logger.exception("Calculation failed")
        return templates.TemplateResponse(
            "result.html",
            {
                "request": request,
                "run_id": run_id,
                "provider": provider,
                "extraction": corrected,
                "step": "review",
                "results": None,
                "error": f"Calculation error: {e}",
            },
        )

    result_dict = json.loads(result.model_dump_json())

    # Update DB
    with get_db() as db:
        db.execute(
            "UPDATE sizing_runs SET corrected_values = ?, results = ?, status = 'calculated' WHERE id = ?",
            (json.dumps(corrected), json.dumps(result_dict), run_id),
        )

    return templates.TemplateResponse(
        "result.html",
        {
            "request": request,
            "run_id": run_id,
            "provider": provider,
            "extraction": corrected,
            "step": "results",
            "results": result_dict,
        },
    )


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    runs = insights.get_run_history()
    # Parse JSON fields for display
    for run in runs:
        if run.get("results"):
            try:
                run["results_parsed"] = json.loads(run["results"])
            except (json.JSONDecodeError, TypeError):
                run["results_parsed"] = None
    return templates.TemplateResponse(
        "history.html", {"request": request, "runs": runs}
    )
