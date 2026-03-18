"""New Relic → Coralogix sizing calculation engine.

NR Data Management gives "Avg daily ingest" in GB directly per source.
We map each NR source to a Coralogix signal (Logs, Metrics, Traces, RUM).
"""

from decimal import Decimal

from app.models import NewRelicExtraction, SizingResult

D = Decimal

# ---------------------------------------------------------------------------
# NR Source → CX Signal mapping (from Notion KB)
# ---------------------------------------------------------------------------
# Logs:    Logging, Custom events, Serverless, Security Bytes
# Metrics: Metrics, Infrastructure Integrations, Infrastructure Hosts, Infrastructure Processes
# Traces:  APM events, Tracing
# RUM:     Browser events, Mobile events


def _val(v: float | None) -> Decimal:
    return D(str(v)) if v is not None else D("0")


def calculate(ext: NewRelicExtraction) -> SizingResult:
    warnings: list[str] = []
    details: dict = {}

    # ------------------------------------------------------------------
    # LOGS = Logging + Custom events + Serverless + Security
    # ------------------------------------------------------------------
    logs_sources = {
        "Logging": ext.logging_gb_day,
        "Custom events": ext.custom_events_gb_day,
        "Serverless": ext.serverless_gb_day,
        "Security Bytes": ext.security_bytes_gb_day,
    }
    logs_gb_day = D("0")
    for name, val in logs_sources.items():
        gb = _val(val)
        logs_gb_day += gb
        details[f"logs_{name.lower().replace(' ', '_')}_gb_day"] = str(gb.quantize(D("0.01")))

    if ext.logging_gb_day is None:
        warnings.append("MISSING: 'Logging' source not found in screenshot")

    # ------------------------------------------------------------------
    # METRICS = Metrics + Infra Integrations + Infra Hosts + Infra Processes
    # NumSeries = total_metrics_gb_day × 1000
    # ------------------------------------------------------------------
    metrics_sources = {
        "Metrics": ext.metrics_gb_day,
        "Infrastructure Integrations": ext.infra_integrations_gb_day,
        "Infrastructure Hosts": ext.infra_hosts_gb_day,
        "Infrastructure Processes": ext.infra_processes_gb_day,
    }
    total_metrics_gb_day = D("0")
    for name, val in metrics_sources.items():
        gb = _val(val)
        total_metrics_gb_day += gb
        details[f"metrics_{name.lower().replace(' ', '_')}_gb_day"] = str(
            gb.quantize(D("0.01"))
        )

    metrics_num_series = int(total_metrics_gb_day * 1000)

    if ext.metrics_gb_day is None:
        warnings.append("MISSING: 'Metrics' source not found in screenshot")

    warnings.append(
        f"NOTE: NumSeries ({metrics_num_series:,}) is estimated from NR metric GB "
        f"({total_metrics_gb_day.quantize(D('0.01'))} GB/day × 1,000). "
        "For a more accurate count, ask the customer to run: "
        "SELECT uniqueCount(metricName) FROM Metric SINCE 1 day ago"
    )

    details["metrics_num_series"] = str(metrics_num_series)
    details["metrics_source"] = "Estimated from NR metric GB × 1000"

    # ------------------------------------------------------------------
    # TRACES = APM events + Tracing
    # ------------------------------------------------------------------
    traces_sources = {
        "APM events": ext.apm_events_gb_day,
        "Tracing": ext.tracing_gb_day,
    }
    traces_gb_day = D("0")
    for name, val in traces_sources.items():
        gb = _val(val)
        traces_gb_day += gb
        details[f"traces_{name.lower().replace(' ', '_')}_gb_day"] = str(
            gb.quantize(D("0.01"))
        )

    if ext.apm_events_gb_day is None and ext.tracing_gb_day is None:
        warnings.append("MISSING: No APM events or Tracing data found in screenshot")

    # ------------------------------------------------------------------
    # RUM = Browser events + Mobile events
    # ------------------------------------------------------------------
    rum_sources = {
        "Browser events": ext.browser_events_gb_day,
        "Mobile events": ext.mobile_events_gb_day,
    }
    rum_gb_day = D("0")
    for name, val in rum_sources.items():
        gb = _val(val)
        rum_gb_day += gb
        details[f"rum_{name.lower().replace(' ', '_')}_gb_day"] = str(gb.quantize(D("0.01")))

    return SizingResult(
        provider="newrelic",
        logs_gb_day=logs_gb_day.quantize(D("0.01")),
        metrics_num_series=metrics_num_series,
        metrics_gb_day=total_metrics_gb_day.quantize(D("0.01")),
        traces_gb_day=traces_gb_day.quantize(D("0.01")),
        rum_gb_day=rum_gb_day.quantize(D("0.01")),
        rum_sessions_day=None,
        warnings=warnings,
        details=details,
    )
