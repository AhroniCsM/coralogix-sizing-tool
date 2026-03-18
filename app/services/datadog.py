"""Datadog → Coralogix sizing calculation engine.

All math uses Decimal to avoid float rounding issues on pricing-sensitive data.
Formulas sourced from the official SE team spreadsheets (Tango, BigId).
"""

from decimal import Decimal

from app.models import DatadogExtraction, SizingResult

# ---------------------------------------------------------------------------
# Constants (from official DD-to-CX spreadsheet)
# ---------------------------------------------------------------------------
AVG_LOG_SIZE_KB = Decimal("2.0")
AVG_SPAN_SIZE_KB = Decimal("1.5")
TS_PER_NODE = Decimal("750")
TS_TO_UNITS = Decimal("0.000033")

D = Decimal  # shorthand


def _hourly_to_count(hourly_value: float) -> Decimal:
    """Convert Datadog hourly metric to monthly count: hours / 30 / 24 * 1.1"""
    return D(str(hourly_value)) / 30 / 24 * D("1.1")


def _val(v: float | None) -> Decimal:
    """Safe conversion: None → 0, float → Decimal."""
    return D(str(v)) if v is not None else D("0")


def _resolve_host_field(
    value: float | None, is_hourly: bool | None
) -> Decimal:
    """Resolve a host/container field, converting from hours if needed."""
    if value is None:
        return D("0")
    if is_hourly:
        return _hourly_to_count(value)
    return D(str(value))


def calculate(ext: DatadogExtraction) -> SizingResult:
    warnings: list[str] = []
    details: dict = {}

    # ------------------------------------------------------------------
    # HOSTS & CONTAINERS (with hourly conversion)
    # ------------------------------------------------------------------
    infra_hosts = _resolve_host_field(ext.infra_hosts, ext.infra_hosts_is_hourly)
    apm_hosts = _resolve_host_field(ext.apm_hosts, ext.apm_hosts_is_hourly)
    profiled_hosts = _resolve_host_field(ext.profiled_hosts, ext.profiled_hosts_is_hourly)
    network_hosts = _resolve_host_field(ext.network_hosts, ext.network_hosts_is_hourly)
    fargate_tasks = _val(ext.fargate_tasks)

    total_hosts = infra_hosts + apm_hosts + profiled_hosts + network_hosts + fargate_tasks

    # Containers — container_hours always needs conversion
    containers = _hourly_to_count(ext.container_hours) if ext.container_hours else D("0")
    profiled_containers = _resolve_host_field(
        ext.profiled_containers, ext.profiled_containers_is_hourly
    )
    total_containers = containers + profiled_containers

    details["infra_hosts"] = str(infra_hosts.quantize(D("1")))
    details["apm_hosts"] = str(apm_hosts.quantize(D("1")))
    details["profiled_hosts"] = str(profiled_hosts.quantize(D("1")))
    details["network_hosts"] = str(network_hosts.quantize(D("1")))
    details["fargate_tasks"] = str(fargate_tasks.quantize(D("1")))
    details["total_hosts"] = str(total_hosts.quantize(D("1")))
    details["containers"] = str(containers.quantize(D("1")))
    details["profiled_containers"] = str(profiled_containers.quantize(D("1")))
    details["total_containers"] = str(total_containers.quantize(D("1")))

    # ------------------------------------------------------------------
    # LOGS
    # ------------------------------------------------------------------
    ingested_logs_gb = _val(ext.ingested_logs_gb)
    analyzed_security_gb = _val(ext.analyzed_logs_security_gb)
    total_ingested_gb = ingested_logs_gb + analyzed_security_gb

    # Indexed logs fallback
    idx_3d = _val(ext.indexed_logs_3d)
    idx_7d = _val(ext.indexed_logs_7d)
    idx_15d = _val(ext.indexed_logs_15d)
    idx_live = _val(ext.indexed_logs_live)
    idx_90d = _val(ext.indexed_logs_90d)
    total_indexed_millions = idx_3d + idx_7d + idx_15d + idx_live + idx_90d
    total_indexed_logs = total_indexed_millions * D("1000000")
    total_indexed_bytes = total_indexed_logs * AVG_LOG_SIZE_KB * 1024
    total_indexed_gb_month = total_indexed_bytes / D(str(1024**3))
    total_indexed_gb_day = total_indexed_gb_month / 30

    if total_ingested_gb > 0:
        logs_gb_day = total_ingested_gb / 30
    elif total_indexed_gb_day > 0:
        logs_gb_day = total_indexed_gb_day
        warnings.append(
            "FALLBACK: Using indexed logs to estimate volume — "
            "ingested logs not found in screenshot. "
            f"Indexed: {total_indexed_millions}M logs × {AVG_LOG_SIZE_KB} KB avg = "
            f"{total_indexed_gb_day.quantize(D('0.01'))} GB/day"
        )
    else:
        logs_gb_day = D("0")
        warnings.append("MISSING: No log data found in screenshots (ingested or indexed)")

    if total_ingested_gb > 0 and total_indexed_gb_month > 0:
        indexed_pct = (total_indexed_gb_month / total_ingested_gb * 100).quantize(D("0.01"))
        details["logs_indexed_pct"] = str(indexed_pct)

    details["logs_ingested_gb_month"] = str(total_ingested_gb.quantize(D("0.01")))
    details["logs_indexed_millions"] = str(total_indexed_millions.quantize(D("0.01")))

    # ------------------------------------------------------------------
    # METRICS (NumSeries)
    # ------------------------------------------------------------------
    custom_metrics = _resolve_host_field(ext.custom_metrics, ext.custom_metrics_is_hourly)

    # Serverless TS
    serverless_funcs = _val(ext.serverless_functions)
    serverless_invocations = _val(ext.serverless_invocations)
    if serverless_funcs > 0:
        serverless_ts = serverless_funcs * 15 * 24
    elif serverless_invocations > 0:
        serverless_ts = serverless_invocations * D("0.3")
    else:
        serverless_ts = D("0")

    # Calculated NumSeries from infrastructure
    infra_ts = (total_hosts + total_containers) * TS_PER_NODE + serverless_ts
    calculated_num_series = infra_ts + custom_metrics

    # ALWAYS use calculated NumSeries (matches real SE spreadsheet methodology).
    # Metrics Overview includes internal/system metrics not relevant for CX sizing.
    metrics_num_series = int(calculated_num_series)
    details["metrics_source"] = "Calculated from infrastructure"

    # If Metrics Overview available, show as reference for validation only
    if ext.total_metrics_from_overview is not None and ext.total_metrics_from_overview > 0:
        overview_val = int(D(str(ext.total_metrics_from_overview)))
        details["metrics_overview_reference"] = str(overview_val)
        if calculated_num_series > 0:
            ratio = D(str(overview_val)) / calculated_num_series
            if ratio > 2 or ratio < D("0.5"):
                warnings.append(
                    f"NOTE: Metrics Overview shows {overview_val:,} but infrastructure "
                    f"calculation gives {metrics_num_series:,}. Using calculated value "
                    f"(Metrics Overview includes internal metrics not relevant for CX sizing)."
                )

    metrics_gb_day = D(str(metrics_num_series)) / 1000

    details["infra_ts"] = str(int(infra_ts))
    details["custom_metrics"] = str(int(custom_metrics))
    details["serverless_ts"] = str(int(serverless_ts))
    details["total_num_series"] = str(metrics_num_series)

    # ------------------------------------------------------------------
    # TRACES
    # ------------------------------------------------------------------
    ingested_spans_gb_month = _val(ext.ingested_spans_gb)
    indexed_spans_m = _val(ext.indexed_spans_million)
    custom_events_count = _val(ext.custom_events)

    traces_gb_day = ingested_spans_gb_month / 30

    indexed_spans_gb_month = (
        (indexed_spans_m * D("1000000") + custom_events_count)
        * AVG_SPAN_SIZE_KB / D("1024") / D("1024")
    )

    if ingested_spans_gb_month > 0 and indexed_spans_gb_month > 0:
        idx_span_pct = (indexed_spans_gb_month / ingested_spans_gb_month * 100).quantize(D("0.01"))
        details["traces_indexed_pct"] = str(idx_span_pct)

    traces_indexed_gb_day = D("0")
    traces_archive_gb_day = D("0")
    if traces_gb_day > 0 and ingested_spans_gb_month > 0 and indexed_spans_gb_month > 0:
        pct = indexed_spans_gb_month / ingested_spans_gb_month
        traces_indexed_gb_day = (traces_gb_day * pct).quantize(D("0.01"))
        traces_archive_gb_day = traces_gb_day - traces_indexed_gb_day

    if ingested_spans_gb_month == 0 and indexed_spans_m > 0:
        traces_gb_day = indexed_spans_gb_month / 30
        warnings.append(
            "FALLBACK: Using indexed spans to estimate trace volume — "
            f"ingested spans not found. {indexed_spans_m}M spans × "
            f"{AVG_SPAN_SIZE_KB} KB = {traces_gb_day.quantize(D('0.01'))} GB/day"
        )
    elif ingested_spans_gb_month == 0 and indexed_spans_m == 0:
        warnings.append("MISSING: No trace/span data found in screenshots")

    details["traces_ingested_gb_month"] = str(ingested_spans_gb_month.quantize(D("0.01")))
    details["traces_indexed_gb_day"] = str(traces_indexed_gb_day.quantize(D("0.01")))
    details["traces_archive_gb_day"] = str(traces_archive_gb_day.quantize(D("0.01")))

    # ------------------------------------------------------------------
    # RUM
    # ------------------------------------------------------------------
    rum_sessions_monthly = _val(ext.rum_sessions)
    error_tracking = _val(ext.error_tracking_events)
    rum_sessions_day = int(rum_sessions_monthly / D("30.4")) if rum_sessions_monthly > 0 else None
    rum_errors_day = int(error_tracking / 30) if error_tracking > 0 else 0

    # RUM GB is tiny — calculate for completeness
    rum_gb_day = D("0")
    if rum_sessions_day:
        rum_gb_day = (
            (D(str(rum_errors_day)) * 2 + D(str(rum_sessions_day)) * D("800") / 1024) / 1024
        ).quantize(D("0.01"))

    if rum_sessions_monthly == 0:
        warnings.append("MISSING: No RUM session data found in screenshots")

    details["rum_sessions_day"] = str(rum_sessions_day or 0)
    details["rum_errors_day"] = str(rum_errors_day)

    return SizingResult(
        provider="datadog",
        logs_gb_day=logs_gb_day.quantize(D("0.01")),
        metrics_num_series=metrics_num_series,
        metrics_gb_day=metrics_gb_day.quantize(D("0.01")),
        traces_gb_day=traces_gb_day.quantize(D("0.01")),
        rum_gb_day=rum_gb_day,
        rum_sessions_day=rum_sessions_day,
        warnings=warnings,
        details=details,
    )
