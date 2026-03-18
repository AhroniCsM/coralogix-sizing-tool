"""AWS CloudWatch → Coralogix sizing calculation engine.

CloudWatch billing is per-region; we aggregate totals across all regions.
Conversion formulas from the Coralogix Notion SE guide:
  - Logs: CW PutLogEvents GB is raw uncompressed. CX enrichment multiplier = 1.77x
    (avg CW log ~455 bytes → ~805 bytes in CX).
  - Metrics: custom_metrics_count maps directly to NumSeries.
  - Traces: X-Ray: 5 KB/trace, 2 KB/segment → GB/day.
"""

from decimal import Decimal

from app.models import CloudWatchExtraction, SizingResult

D = Decimal

# CW → CX enrichment multiplier (455 bytes avg CW → 805 bytes avg CX)
CX_LOG_ENRICHMENT_MULTIPLIER = D("1.77")

# X-Ray sizing constants (KB per unit)
XRAY_KB_PER_TRACE = D("5")
XRAY_KB_PER_SEGMENT = D("2")

# Bytes in a GB
GB = D(str(1024 * 1024))  # in KB


def _val(v: float | None) -> Decimal:
    """Safe conversion: None → 0, float → Decimal."""
    return D(str(v)) if v is not None else D("0")


def calculate(ext: CloudWatchExtraction) -> SizingResult:
    warnings: list[str] = []
    details: dict = {}

    # ------------------------------------------------------------------
    # LOGS — PutLogEvents GB (monthly) → daily, with CX enrichment
    # ------------------------------------------------------------------
    put_log_gb = _val(ext.total_put_log_events_gb)

    if put_log_gb > 0:
        logs_gb_day = (put_log_gb / 30) * CX_LOG_ENRICHMENT_MULTIPLIER
        details["logs_put_log_events_gb_month"] = str(put_log_gb.quantize(D("0.01")))
        details["logs_cx_enrichment_multiplier"] = str(CX_LOG_ENRICHMENT_MULTIPLIER)
    else:
        logs_gb_day = D("0")
        warnings.append(
            "MISSING: No PutLogEvents data found — cannot estimate log volume"
        )

    # Storage info (informational, not used for CX sizing)
    storage_gb_mo = _val(ext.total_timed_storage_gb_mo)
    if storage_gb_mo > 0:
        details["logs_timed_storage_gb_mo"] = str(storage_gb_mo.quantize(D("0.01")))

    # S3 egress (informational)
    s3_egress = _val(ext.total_s3_egress_gb)
    if s3_egress > 0:
        details["logs_s3_egress_gb"] = str(s3_egress.quantize(D("0.01")))

    # Log Insights scanned (informational)
    start_query_gb = _val(ext.total_start_query_gb)
    if start_query_gb > 0:
        details["logs_insights_scanned_gb"] = str(start_query_gb.quantize(D("0.01")))

    details["logs_gb_day_before_enrichment"] = str(
        (put_log_gb / 30).quantize(D("0.01")) if put_log_gb > 0 else D("0")
    )

    # ------------------------------------------------------------------
    # METRICS — custom metrics count → NumSeries
    # ------------------------------------------------------------------
    custom_metrics = _val(ext.total_custom_metrics_count)
    metric_updates = _val(ext.total_metric_updates)
    metric_api_requests = _val(ext.total_metric_api_requests)
    alarms = _val(ext.total_alarms_count)

    if custom_metrics > 0:
        metrics_num_series = int(custom_metrics)
        details["metrics_source"] = "CloudWatch custom metrics count"
    elif metric_updates > 0:
        # Rough estimate: each metric gets ~1 update per minute → 43,200/month
        metrics_num_series = max(1, int(metric_updates / 43200))
        details["metrics_source"] = "Estimated from metric updates (updates / 43200)"
        warnings.append(
            f"NOTE: NumSeries ({metrics_num_series:,}) estimated from metric updates "
            f"({int(metric_updates):,}). For accuracy, ask customer to run: "
            "aws cloudwatch list-metrics | wc -l"
        )
    else:
        metrics_num_series = 0
        warnings.append(
            "MISSING: No custom metrics count found. Ask customer to run: "
            "aws cloudwatch list-metrics | wc -l"
        )

    metrics_gb_day = D(str(metrics_num_series)) / 1000

    details["metrics_custom_count"] = str(int(custom_metrics))
    details["metrics_api_requests"] = str(int(metric_api_requests))
    details["metrics_updates"] = str(int(metric_updates))
    details["metrics_alarms"] = str(int(alarms))
    details["metrics_num_series"] = str(metrics_num_series)

    # ------------------------------------------------------------------
    # TRACES — X-Ray traces + segments → GB/day
    # ------------------------------------------------------------------
    xray_traces = _val(ext.total_xray_traces)
    xray_segments = _val(ext.total_xray_segments)

    if xray_traces > 0 or xray_segments > 0:
        # (traces * 5KB + segments * 2KB) / (1024 * 1024) = GB/day
        traces_kb = xray_traces * XRAY_KB_PER_TRACE + xray_segments * XRAY_KB_PER_SEGMENT
        traces_gb_day = traces_kb / GB
        details["traces_xray_traces"] = str(int(xray_traces))
        details["traces_xray_segments"] = str(int(xray_segments))
    else:
        traces_gb_day = D("0")
        warnings.append("MISSING: No X-Ray trace/segment data found in screenshots")

    # ------------------------------------------------------------------
    # Per-region breakdown (informational)
    # ------------------------------------------------------------------
    if ext.regions:
        details["region_count"] = str(len(ext.regions))
        for region_name, region_data in ext.regions.items():
            prefix = f"region_{region_name}"
            if isinstance(region_data, dict):
                for k, v in region_data.items():
                    if v is not None:
                        details[f"{prefix}_{k}"] = str(v)

    # Total CW cost (informational)
    total_cost = _val(ext.total_cloudwatch_cost)
    if total_cost > 0:
        details["cloudwatch_total_cost_usd"] = str(total_cost.quantize(D("0.01")))

    return SizingResult(
        provider="cloudwatch",
        logs_gb_day=logs_gb_day.quantize(D("0.01")),
        metrics_num_series=metrics_num_series,
        metrics_gb_day=metrics_gb_day.quantize(D("0.01")),
        traces_gb_day=traces_gb_day.quantize(D("0.01")),
        rum_gb_day=D("0"),
        rum_sessions_day=None,
        warnings=warnings,
        details=details,
    )
