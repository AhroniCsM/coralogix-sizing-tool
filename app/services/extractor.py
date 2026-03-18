"""OpenAI GPT-4o Vision service for extracting billing values from screenshots.

Sends screenshots to GPT-4o with structured JSON extraction prompts.
Appends dynamic hints from past feedback (extraction_insights table).
"""

import base64
import json
import logging
from pathlib import Path

import openai

from app.config import settings
from app.models import DatadogExtraction, NewRelicExtraction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

DATADOG_PROMPT = """You are an expert Coralogix SE analyzing Datadog billing screenshots to produce accurate sizing estimates.
You have been calibrated against 16 real customer conversions. Extract ALL fields listed below.

CRITICAL RULES:
- Report the RAW value from the screenshot exactly as shown
- For each field, note if the label says "Hours" (e.g., "Infra Host Hours", "Container Hours")
- Parse suffixes: K = 1,000 / M = 1,000,000 / B = 1,000,000,000 / TB = 1,000 GB
- If a field is not visible in the screenshots, set it to null
- DO NOT estimate or calculate — only extract what you see
- For "Indexed Logs" with retention labels like "(3 Day Retention)", extract the number in millions
- "Ingested Spans" may be in GB or TB — THIS IS THE #1 ERROR, check the suffix very carefully!
- On-Demand sub-labels show the same number — ignore them, just use the main value
- If you see a "Metrics Overview" screenshot, extract "Total Metrics" from the top-right number
- IMPORTANT: Make sure you're reading from the BILLABLE tab (not "All")
- "Analyzed Logs (Security)" is a SEPARATE line item from "Ingested Logs" — you MUST extract BOTH! They are added together for total log volume. This is the #2 most common extraction error.
- Example: "Analyzed Logs (Security): 3,270 GB" → analyzed_logs_security_gb = 3270. Do NOT add this to ingested_logs_gb.

TYPICAL VALUE RANGES (from 16 real customers — use for sanity checking):
- Infra Hosts: 65 to 4,094 (often shown as hourly: 46K–2.8M hours)
- APM Hosts: 0 to 700 (hourly: 0–510K hours)
- Containers: 0 to 15,431 (always shown as hours: 0–11M hours)
- Custom Metrics: 135 to 435,417 (may show as hourly)
- Ingested Logs: 0 to 404,000 GB/month
- Ingested Spans: 0 to 67,000 GB/month (WATCH: 67 TB = 67,000 GB, not 67 GB!)
- Indexed Spans: 0 to 1,740 million/month
- RUM Sessions: 0 to 5,296/month (many customers have 0)
- Serverless Invocations: 0 to 21M/month

Return ONLY valid JSON matching this schema:
{
  "infra_hosts": <number or null>,
  "infra_hosts_is_hourly": <true if label says "Hours", false otherwise>,
  "apm_hosts": <number or null>,
  "apm_hosts_is_hourly": <true if label says "Hours", false otherwise>,
  "profiled_hosts": <number or null>,
  "profiled_hosts_is_hourly": <true if label says "Hours", false otherwise>,
  "network_hosts": <number or null>,
  "network_hosts_is_hourly": <true if label says "Hours", false otherwise>,
  "fargate_tasks": <number or null>,
  "container_hours": <number or null — this is ALWAYS hourly>,
  "profiled_containers": <number or null>,
  "profiled_containers_is_hourly": <true if label says "Hours", false otherwise>,
  "custom_metrics": <number or null>,
  "custom_metrics_is_hourly": <true if label says "Hours", false otherwise>,
  "indexed_logs_3d": <number in MILLIONS or null>,
  "indexed_logs_7d": <number in MILLIONS or null>,
  "indexed_logs_15d": <number in MILLIONS or null>,
  "indexed_logs_live": <number in MILLIONS or null>,
  "indexed_logs_90d": <number in MILLIONS or null>,
  "ingested_logs_gb": <number in GB or null>,
  "analyzed_logs_security_gb": <number in GB or null — CRITICAL: look for "Analyzed Logs (Security)" separately!>,
  "ingested_spans_gb": <number in GB or null — convert TB to GB if needed>,
  "indexed_spans_million": <number in MILLIONS or null>,
  "custom_events": <number or null>,
  "serverless_functions": <number or null>,
  "serverless_invocations": <number or null>,
  "rum_sessions": <number or null>,
  "error_tracking_events": <number or null>,
  "total_metrics_from_overview": <number or null — from Metrics Overview screenshot>,
  "missing_fields": [<list of field names not found in screenshots>],
  "confidence": {<field_name>: "high"|"medium"|"low" for fields where you're uncertain}
}

IMPORTANT UNIT CONVERSIONS to apply before returning:
- If "Indexed Logs (3 Day Retention): 20.8B" → indexed_logs_3d = 20800 (convert B to M)
- If "Ingested Spans: 66.7 TB" → ingested_spans_gb = 66700 (convert TB to GB)
- If "Container Hours: 2.72M" → container_hours = 2720000 (raw number, we convert later)
- If "Custom Metrics: 2.69K" → custom_metrics = 2690
- If "Total Metrics: 7.07M" → total_metrics_from_overview = 7070000
"""

NEWRELIC_PROMPT = """You are an expert Coralogix SE analyzing a New Relic Data Management screenshot.
You have been calibrated against 11 real customer conversions.

The screenshot shows a table with columns: Source, Avg daily ingest, Last 30 days, % of total.

Extract the "Avg daily ingest" value (in GB) for each of these sources.
If a source is not visible, set it to null.

TYPICAL VALUE RANGES (from 11 real customers — use for sanity checking):
- Logging: 0 to 4,187 GB/day (can be 0 for metrics-heavy customers)
- Metrics: 9 to 7,433 GB/day
- Infrastructure Integrations: 0 to 2,300 GB/day
- Infrastructure Hosts: 0 to 95 GB/day
- Infrastructure Processes: 0 to 1,170 GB/day
- APM events: 0 to 7,753 GB/day
- Tracing: 10 to 3,942 GB/day
- Browser events: 0 to 504 GB/day
- Custom events: 0 to 3,145 GB/day (usually mapped to Logs, sometimes Traces)
- Mobile events: rare, usually 0
- Serverless: rare, usually 0

Return ONLY valid JSON matching this schema:
{
  "logging_gb_day": <number in GB or null>,
  "custom_events_gb_day": <number in GB or null>,
  "serverless_gb_day": <number in GB or null>,
  "security_bytes_gb_day": <number in GB or null>,
  "metrics_gb_day": <number in GB or null>,
  "infra_integrations_gb_day": <number in GB or null>,
  "infra_hosts_gb_day": <number in GB or null>,
  "infra_processes_gb_day": <number in GB or null>,
  "apm_events_gb_day": <number in GB or null>,
  "tracing_gb_day": <number in GB or null>,
  "browser_events_gb_day": <number in GB or null>,
  "mobile_events_gb_day": <number in GB or null>,
  "missing_fields": [<list of source names not found>],
  "confidence": {<field_name>: "high"|"medium"|"low" for uncertain fields}
}

ALSO extract from the page header if visible:
- Total daily average (e.g., "9,704 GB Daily average")
- Total last 30 days (e.g., "291,142 GB Last 30 days")
- Account name/ID

Include these as extra fields: "total_daily_gb", "total_30d_gb", "account_info".
"""


def _image_to_base64_url(path: Path) -> str:
    """Read an image file and return a data URL for OpenAI vision."""
    suffix = path.suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_types.get(suffix, "image/png")
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{media_type};base64,{data}"


def _parse_json_response(raw_text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    json_str = raw_text
    if "```" in json_str:
        if "```json" in json_str:
            json_str = json_str.split("```json")[-1].split("```")[0]
        else:
            json_str = json_str.split("```")[1].split("```")[0]
    data = json.loads(json_str.strip())

    # Sanitize: coerce null booleans to False (GPT-4o returns null when unsure)
    for key in list(data.keys()):
        if key.endswith("_is_hourly") and data[key] is None:
            data[key] = False

    return data


async def extract_datadog(
    screenshot_paths: list[Path],
    hints: list[str] | None = None,
) -> DatadogExtraction:
    """Extract Datadog billing values from screenshots using GPT-4o Vision."""
    client = openai.OpenAI(api_key=settings.openai_api_key)

    # Build content blocks: images first, then prompt
    content: list[dict] = []
    for path in screenshot_paths:
        url = _image_to_base64_url(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": url, "detail": "high"},
        })

    prompt = DATADOG_PROMPT
    if hints:
        prompt += "\n\nLEARNED HINTS FROM PAST EXTRACTIONS:\n"
        for hint in hints:
            prompt += f"- {hint}\n"

    content.append({"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = response.choices[0].message.content
    logger.info("Datadog extraction raw response: %s", raw_text[:500])

    data = _parse_json_response(raw_text)
    return DatadogExtraction(**data)


async def extract_newrelic(
    screenshot_paths: list[Path],
    hints: list[str] | None = None,
) -> NewRelicExtraction:
    """Extract New Relic Data Management values from screenshot using GPT-4o Vision."""
    client = openai.OpenAI(api_key=settings.openai_api_key)

    content: list[dict] = []
    for path in screenshot_paths:
        url = _image_to_base64_url(path)
        content.append({
            "type": "image_url",
            "image_url": {"url": url, "detail": "high"},
        })

    prompt = NEWRELIC_PROMPT
    if hints:
        prompt += "\n\nLEARNED HINTS FROM PAST EXTRACTIONS:\n"
        for hint in hints:
            prompt += f"- {hint}\n"

    content.append({"type": "text", "text": prompt})

    response = client.chat.completions.create(
        model=settings.openai_model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )

    raw_text = response.choices[0].message.content
    logger.info("New Relic extraction raw response: %s", raw_text[:500])

    data = _parse_json_response(raw_text)
    return NewRelicExtraction(**data)
