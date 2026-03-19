"""Sizing router — upload screenshots, extract values, calculate results."""

import base64
import json
import logging
import shutil
import uuid
from decimal import Decimal as D
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import BASE_DIR, settings
from app.database import get_db
from app.models import CloudWatchExtraction, DatadogExtraction, NewRelicExtraction
from app.services import cloudwatch, datadog, extractor, insights, newrelic, pricing

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@router.get("/tco", response_class=HTMLResponse)
async def tco_calculator(request: Request, run_id: int = 0):
    """Show TCO calculator, optionally pre-filled from a sizing run."""
    prefill: dict = {}
    if run_id:
        try:
            with get_db() as db:
                row = db.execute(
                    "SELECT provider, results FROM sizing_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if row and row["results"]:
                    results = json.loads(row["results"])
                    prefill = {
                        "logs_gb_day": float(results.get("logs_gb_day", 0)),
                        "metrics_num_series": int(results.get("metrics_num_series", 0)),
                        "traces_gb_day": float(results.get("traces_gb_day", 0)),
                        "rum_gb_day": float(results.get("rum_gb_day", 0)),
                        "provider": row["provider"],
                    }
        except Exception:
            logger.exception("Failed to load run for TCO prefill")
    return templates.TemplateResponse("tco.html", {"request": request, "prefill": prefill})


@router.post("/upload")
async def upload(
    request: Request,
    provider: str = Form(...),
    screenshots: list[UploadFile] = File(...),
):
    """Save screenshots, run GPT-4o Vision extraction, show review form."""
    # Validate provider
    if provider not in ("datadog", "newrelic", "cloudwatch"):
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": "Invalid provider. Choose Datadog, New Relic, or CloudWatch."},
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

    # Extract values using GPT-4o Vision
    try:
        if provider == "datadog":
            result = await extractor.extract_datadog(saved_paths, hints)
        elif provider == "cloudwatch":
            result = await extractor.extract_cloudwatch(saved_paths, hints)
        else:
            result = await extractor.extract_newrelic(saved_paths, hints)
    except Exception as e:
        logger.exception("Extraction failed")
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "error": f"Extraction failed: {e}"},
            status_code=500,
        )

    # Store run in DB
    extraction_dict = result.extraction.model_dump()
    user = request.session.get("user")
    user_email = user["email"] if user else None
    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO sizing_runs
               (provider, raw_extraction, screenshot_paths, missing_fields, user_email,
                prompt_tokens, completion_tokens, api_cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                provider,
                json.dumps(extraction_dict),
                json.dumps([str(p) for p in saved_paths]),
                json.dumps(extraction_dict.get("missing_fields", [])),
                user_email,
                result.prompt_tokens,
                result.completion_tokens,
                result.api_cost_usd,
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


class PastePayload(BaseModel):
    provider: str
    images: list[str]  # base64 data URLs


@router.post("/paste")
async def paste_upload(request: Request, payload: PastePayload):
    """Accept pasted screenshots as base64 data URLs, extract and return run_id."""
    if payload.provider not in ("datadog", "newrelic", "cloudwatch"):
        return JSONResponse({"error": "Invalid provider"}, status_code=400)

    if not payload.images:
        return JSONResponse({"error": "No images pasted"}, status_code=400)

    provider_dir = settings.screenshots_dir / payload.provider
    provider_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for i, data_url in enumerate(payload.images):
        # Parse data URL: "data:image/png;base64,iVBOR..."
        try:
            header, b64_data = data_url.split(",", 1)
            # Extract mime type
            mime = header.split(":")[1].split(";")[0] if ":" in header else "image/png"
            ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                   "image/gif": ".gif"}.get(mime, ".png")
            img_bytes = base64.b64decode(b64_data)
        except Exception:
            continue

        fname = f"{uuid.uuid4().hex[:8]}_paste_{i}{ext}"
        dest = provider_dir / fname
        dest.write_bytes(img_bytes)
        saved_paths.append(dest)

    if not saved_paths:
        return JSONResponse({"error": "Failed to process pasted images"}, status_code=400)

    hints = insights.get_hints(payload.provider)

    try:
        if payload.provider == "datadog":
            result = await extractor.extract_datadog(saved_paths, hints)
        elif payload.provider == "cloudwatch":
            result = await extractor.extract_cloudwatch(saved_paths, hints)
        else:
            result = await extractor.extract_newrelic(saved_paths, hints)
    except Exception as e:
        return JSONResponse({"error": f"Extraction failed: {e}"}, status_code=500)

    extraction_dict = result.extraction.model_dump()
    user = request.session.get("user")
    user_email = user["email"] if user else None
    with get_db() as db:
        cursor = db.execute(
            """INSERT INTO sizing_runs
               (provider, raw_extraction, screenshot_paths, missing_fields, user_email,
                prompt_tokens, completion_tokens, api_cost_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                payload.provider,
                json.dumps(extraction_dict),
                json.dumps([str(p) for p in saved_paths]),
                json.dumps(extraction_dict.get("missing_fields", [])),
                user_email,
                result.prompt_tokens,
                result.completion_tokens,
                result.api_cost_usd,
            ),
        )
        run_id = cursor.lastrowid

    return JSONResponse({
        "run_id": run_id,
        "provider": payload.provider,
        "extraction": extraction_dict,
    })


@router.post("/calculate")
async def calculate(request: Request):
    """Accept corrected values, run formulas, show results."""
    form = await request.form()
    run_id = int(form.get("run_id", 0))
    provider = str(form.get("provider", ""))

    if not run_id or provider not in ("datadog", "newrelic", "cloudwatch"):
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
        elif key == "regions":
            # regions is a JSON dict — parse it back
            try:
                corrected[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                corrected[key] = {}
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
            price_est = pricing.estimate_datadog(ext)
        elif provider == "cloudwatch":
            ext = CloudWatchExtraction(**corrected)
            result = cloudwatch.calculate(ext)
            price_est = pricing.estimate_cloudwatch(ext)
        else:
            ext = NewRelicExtraction(**corrected)
            result = newrelic.calculate(ext)
            price_est = pricing.estimate_newrelic(ext)
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

    # Serialize pricing estimate
    pricing_dict = {
        "provider": price_est.provider,
        "total_list": str(price_est.total_list.quantize(D("0.01"))),
        "total_low": str(price_est.total_low.quantize(D("0.01"))),
        "total_high": str(price_est.total_high.quantize(D("0.01"))),
        "notes": price_est.notes,
        "line_items": [
            {
                "category": li.category,
                "description": li.description,
                "quantity": li.quantity,
                "unit_price": li.unit_price,
                "monthly_list": str(li.monthly_list.quantize(D("0.01"))),
                "monthly_low": str(li.monthly_low.quantize(D("0.01"))),
                "monthly_high": str(li.monthly_high.quantize(D("0.01"))),
            }
            for li in price_est.line_items
        ],
    }

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
            "pricing": pricing_dict,
        },
    )


@router.post("/paste-result")
async def paste_result(request: Request):
    """Render result page from paste API response."""
    form = await request.form()
    run_id = int(form.get("run_id", 0))
    provider = str(form.get("provider", ""))
    extraction_json = str(form.get("extraction", "{}"))

    try:
        extraction_dict = json.loads(extraction_json)
    except json.JSONDecodeError:
        return RedirectResponse("/", status_code=303)

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


@router.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    user = request.session.get("user")
    user_email = user["email"] if user else None
    runs = insights.get_run_history(user_email=user_email)
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
