"""Competitor pricing estimation for Datadog and New Relic.

Calculates estimated monthly spend based on extracted usage data.
Returns a range (low–high) since actual pricing depends on:
- Commitment tier (on-demand vs annual vs 3-year)
- Volume discounts (negotiated enterprise deals are 30–60% off list)
- Bundle deals and custom SKU pricing

List prices sourced from public pricing pages (2024/2025).
"""

from dataclasses import dataclass, field
from decimal import Decimal

from app.models import CloudWatchExtraction, DatadogExtraction, NewRelicExtraction

D = Decimal

# ---------------------------------------------------------------------------
# Datadog pricing (monthly list prices, on-demand / pay-as-you-go)
# ---------------------------------------------------------------------------

DD_PRICING = {
    # Infrastructure Monitoring
    "infra_host_pro": D("15"),          # $15/host/mo (Pro)
    "infra_host_enterprise": D("23"),   # $23/host/mo (Enterprise)

    # APM
    "apm_host_pro": D("31"),            # $31/host/mo (Pro)
    "apm_host_enterprise": D("40"),     # $40/host/mo (Enterprise)

    # Profiling (Continuous Profiler)
    "profiled_host": D("19"),           # $19/host/mo

    # Network Performance Monitoring
    "network_host": D("5"),             # $5/host/mo

    # Containers — included with infra host pricing (5 containers free per host)
    # Additional containers billed at host fraction
    "container_per_unit": D("0.002"),   # ~$0.002/container-hour (derived)

    # Serverless
    "serverless_per_million": D("5"),   # $5/million invocations
    "serverless_function": D("7.20"),   # $7.20/function/mo (APM for serverless)

    # Log Management
    "log_ingest_per_gb": D("0.10"),     # $0.10/GB ingested
    "log_index_per_million_15d": D("1.70"),   # $1.70/M events (15-day retention)
    "log_index_per_million_30d": D("2.50"),   # $2.50/M events (30-day)
    "log_index_per_million_3d": D("1.06"),    # $1.06/M events (3-day)
    "log_index_per_million_7d": D("1.27"),    # $1.27/M events (7-day)
    "log_index_per_million_90d": D("3.00"),   # $3.00/M events (90-day)

    # Security (Analyzed Logs)
    "security_logs_per_gb": D("0.20"),  # $0.20/GB analyzed

    # Traces (APM)
    "ingested_spans_per_gb": D("0.10"),   # $0.10/GB ingested spans
    "indexed_spans_per_million": D("1.70"), # $1.70/M indexed spans

    # Custom Metrics
    "custom_metrics_per_100": D("0.05"),  # ~$0.05 per 100 custom metrics/mo

    # RUM
    "rum_per_1k_sessions": D("1.80"),     # $1.80/1K sessions/mo

    # Error Tracking
    "error_tracking_per_million": D("1"),  # ~$1/M events

    # Synthetics
    "synthetics_api_per_10k": D("5"),      # $5/10K test runs
}

# Enterprise discount ranges (negotiated)
DD_DISCOUNT_LOW = D("0.30")   # 30% off list (small enterprise)
DD_DISCOUNT_HIGH = D("0.55")  # 55% off list (large enterprise commitment)


@dataclass
class PricingLineItem:
    """A single pricing line item."""
    category: str
    description: str
    quantity: str
    unit_price: str
    monthly_list: Decimal
    monthly_low: Decimal  # with high discount
    monthly_high: Decimal  # with low discount


@dataclass
class PricingEstimate:
    """Full pricing estimate with line items and totals."""
    provider: str
    line_items: list[PricingLineItem] = field(default_factory=list)
    total_list: Decimal = D("0")
    total_low: Decimal = D("0")     # best case (high discount)
    total_high: Decimal = D("0")    # worst case (low discount)
    notes: list[str] = field(default_factory=list)


def _hourly_to_count(hours: float) -> int:
    """Convert Datadog hourly billing to monthly count."""
    return max(1, int(hours / 30 / 24 * 1.1))


def estimate_datadog(ext: DatadogExtraction) -> PricingEstimate:
    """Estimate Datadog monthly spend from extracted billing data."""
    est = PricingEstimate(provider="datadog")
    items = est.line_items

    # --- Infrastructure Hosts ---
    hosts = ext.infra_hosts or 0
    if ext.infra_hosts_is_hourly and hosts > 0:
        hosts = _hourly_to_count(hosts)
    if hosts > 0:
        list_price = D(str(hosts)) * DD_PRICING["infra_host_enterprise"]
        items.append(PricingLineItem(
            category="Infrastructure",
            description="Infra Hosts (Enterprise)",
            quantity=f"{hosts:,}",
            unit_price=f"${DD_PRICING['infra_host_enterprise']}/host/mo",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- APM Hosts ---
    apm = ext.apm_hosts or 0
    if ext.apm_hosts_is_hourly and apm > 0:
        apm = _hourly_to_count(apm)
    if apm > 0:
        list_price = D(str(apm)) * DD_PRICING["apm_host_enterprise"]
        items.append(PricingLineItem(
            category="APM",
            description="APM Hosts (Enterprise)",
            quantity=f"{apm:,}",
            unit_price=f"${DD_PRICING['apm_host_enterprise']}/host/mo",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Profiled Hosts ---
    profiled = ext.profiled_hosts or 0
    if ext.profiled_hosts_is_hourly and profiled > 0:
        profiled = _hourly_to_count(profiled)
    if profiled > 0:
        list_price = D(str(profiled)) * DD_PRICING["profiled_host"]
        items.append(PricingLineItem(
            category="Profiling",
            description="Profiled Hosts",
            quantity=f"{profiled:,}",
            unit_price=f"${DD_PRICING['profiled_host']}/host/mo",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Network Hosts ---
    net = ext.network_hosts or 0
    if ext.network_hosts_is_hourly and net > 0:
        net = _hourly_to_count(net)
    if net > 0:
        list_price = D(str(net)) * DD_PRICING["network_host"]
        items.append(PricingLineItem(
            category="Network",
            description="Network Monitoring Hosts",
            quantity=f"{net:,}",
            unit_price=f"${DD_PRICING['network_host']}/host/mo",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Containers ---
    containers = ext.container_hours or 0
    if containers > 0:
        container_count = max(1, int(containers / 30 / 24))
        list_price = D(str(containers)) * DD_PRICING["container_per_unit"]
        items.append(PricingLineItem(
            category="Containers",
            description=f"Container Hours (~{container_count:,} containers)",
            quantity=f"{containers:,.0f} hours",
            unit_price="included w/ hosts + overage",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Fargate Tasks ---
    fargate = ext.fargate_tasks or 0
    if fargate > 0:
        list_price = D(str(fargate)) * D("2")  # ~$2/task/mo
        items.append(PricingLineItem(
            category="Serverless",
            description="Fargate Tasks",
            quantity=f"{fargate:,}",
            unit_price="~$2/task/mo",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Custom Metrics ---
    cm = ext.custom_metrics or 0
    if ext.custom_metrics_is_hourly and cm > 0:
        cm = _hourly_to_count(cm)
    if cm > 0:
        list_price = D(str(cm)) / 100 * DD_PRICING["custom_metrics_per_100"]
        items.append(PricingLineItem(
            category="Metrics",
            description="Custom Metrics",
            quantity=f"{cm:,}",
            unit_price=f"${DD_PRICING['custom_metrics_per_100']}/100 metrics",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Log Ingestion ---
    log_gb = (ext.ingested_logs_gb or 0)
    if log_gb > 0:
        list_price = D(str(log_gb)) * DD_PRICING["log_ingest_per_gb"]
        items.append(PricingLineItem(
            category="Logs",
            description="Log Ingestion",
            quantity=f"{log_gb:,.0f} GB/mo",
            unit_price=f"${DD_PRICING['log_ingest_per_gb']}/GB",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Log Indexing (by retention tier) ---
    for tier_name, field_name, price_key in [
        ("3-day", "indexed_logs_3d", "log_index_per_million_3d"),
        ("7-day", "indexed_logs_7d", "log_index_per_million_7d"),
        ("15-day", "indexed_logs_15d", "log_index_per_million_15d"),
        ("Live", "indexed_logs_live", "log_index_per_million_30d"),
        ("90-day", "indexed_logs_90d", "log_index_per_million_90d"),
    ]:
        val = getattr(ext, field_name, None) or 0
        if val > 0:
            list_price = D(str(val)) * DD_PRICING[price_key]
            items.append(PricingLineItem(
                category="Logs",
                description=f"Indexed Logs ({tier_name} retention)",
                quantity=f"{val:,.0f}M events",
                unit_price=f"${DD_PRICING[price_key]}/M events",
                monthly_list=list_price,
                monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
                monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
            ))

    # --- Security (Analyzed Logs) ---
    sec_gb = ext.analyzed_logs_security_gb or 0
    if sec_gb > 0:
        list_price = D(str(sec_gb)) * DD_PRICING["security_logs_per_gb"]
        items.append(PricingLineItem(
            category="Security",
            description="Analyzed Logs (Security)",
            quantity=f"{sec_gb:,.0f} GB/mo",
            unit_price=f"${DD_PRICING['security_logs_per_gb']}/GB",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Ingested Spans ---
    spans_gb = ext.ingested_spans_gb or 0
    if spans_gb > 0:
        list_price = D(str(spans_gb)) * DD_PRICING["ingested_spans_per_gb"]
        items.append(PricingLineItem(
            category="Traces",
            description="Ingested Spans",
            quantity=f"{spans_gb:,.0f} GB/mo",
            unit_price=f"${DD_PRICING['ingested_spans_per_gb']}/GB",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Indexed Spans ---
    idx_spans = ext.indexed_spans_million or 0
    if idx_spans > 0:
        list_price = D(str(idx_spans)) * DD_PRICING["indexed_spans_per_million"]
        items.append(PricingLineItem(
            category="Traces",
            description="Indexed Spans",
            quantity=f"{idx_spans:,.0f}M spans",
            unit_price=f"${DD_PRICING['indexed_spans_per_million']}/M spans",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Serverless Invocations ---
    inv = ext.serverless_invocations or 0
    if inv > 0:
        millions = D(str(inv)) / 1_000_000
        list_price = millions * DD_PRICING["serverless_per_million"]
        items.append(PricingLineItem(
            category="Serverless",
            description="Serverless Invocations",
            quantity=f"{inv:,.0f}",
            unit_price=f"${DD_PRICING['serverless_per_million']}/M invocations",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- RUM Sessions ---
    rum = ext.rum_sessions or 0
    if rum > 0:
        thousands = D(str(rum)) / 1000
        list_price = thousands * DD_PRICING["rum_per_1k_sessions"]
        items.append(PricingLineItem(
            category="RUM",
            description="RUM Sessions",
            quantity=f"{rum:,}",
            unit_price=f"${DD_PRICING['rum_per_1k_sessions']}/1K sessions",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # --- Error Tracking ---
    err = ext.error_tracking_events or 0
    if err > 0:
        millions = D(str(err)) / 1_000_000
        list_price = millions * DD_PRICING["error_tracking_per_million"]
        items.append(PricingLineItem(
            category="Error Tracking",
            description="Error Tracking Events",
            quantity=f"{err:,}",
            unit_price=f"${DD_PRICING['error_tracking_per_million']}/M events",
            monthly_list=list_price,
            monthly_low=list_price * (1 - DD_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - DD_DISCOUNT_LOW),
        ))

    # Totals
    est.total_list = sum(i.monthly_list for i in items)
    est.total_low = sum(i.monthly_low for i in items)
    est.total_high = sum(i.monthly_high for i in items)

    est.notes = [
        "List prices from Datadog's public pricing page (on-demand rates).",
        "Low estimate assumes ~55% enterprise commitment discount.",
        "High estimate assumes ~30% annual commitment discount.",
        "Actual pricing depends on contract terms, volume, and negotiation.",
        "Container pricing is approximate — Datadog includes 5 free per host.",
    ]

    return est


# ---------------------------------------------------------------------------
# New Relic pricing
# ---------------------------------------------------------------------------

NR_PRICING = {
    # Data ingest (Standard plan)
    "data_per_gb_standard": D("0.30"),     # $0.30/GB (standard, after 100GB free)
    "data_per_gb_data_plus": D("0.50"),    # $0.50/GB (Data Plus plan)

    # Free tier
    "free_gb_per_month": 100,              # 100 GB/month free

    # User seats (monthly, pay-as-you-go)
    "full_platform_user": D("349"),        # $349/user/mo (Full Platform)
    "core_user": D("49"),                  # $49/user/mo (Core)
    "basic_user": D("0"),                  # Free
}

# New Relic discount ranges
NR_DISCOUNT_LOW = D("0.20")    # 20% off (small commitment)
NR_DISCOUNT_HIGH = D("0.50")   # 50% off (large annual commitment)

# Typical user counts for estimation (since we don't have user seat data)
NR_TYPICAL_USERS_LOW = 5       # small team
NR_TYPICAL_USERS_HIGH = 20     # larger team


def estimate_newrelic(ext: NewRelicExtraction) -> PricingEstimate:
    """Estimate New Relic monthly spend from extracted data management values."""
    est = PricingEstimate(provider="newrelic")
    items = est.line_items

    # Calculate total daily ingest
    sources = [
        ("Logging", ext.logging_gb_day),
        ("Custom Events", ext.custom_events_gb_day),
        ("Serverless", ext.serverless_gb_day),
        ("Security Bytes", ext.security_bytes_gb_day),
        ("Metrics", ext.metrics_gb_day),
        ("Infra Integrations", ext.infra_integrations_gb_day),
        ("Infra Hosts", ext.infra_hosts_gb_day),
        ("Infra Processes", ext.infra_processes_gb_day),
        ("APM Events", ext.apm_events_gb_day),
        ("Tracing", ext.tracing_gb_day),
        ("Browser Events", ext.browser_events_gb_day),
        ("Mobile Events", ext.mobile_events_gb_day),
    ]

    total_daily = sum(v or 0 for _, v in sources)
    total_monthly = D(str(total_daily)) * 30

    # Use overview totals if available
    if hasattr(ext, "total_daily_gb") and ext.total_daily_gb:
        total_daily = ext.total_daily_gb
        total_monthly = D(str(total_daily)) * 30

    # Data ingest line items per source
    for name, daily_val in sources:
        if not daily_val or daily_val <= 0:
            continue
        monthly_gb = D(str(daily_val)) * 30
        list_price = monthly_gb * NR_PRICING["data_per_gb_standard"]
        items.append(PricingLineItem(
            category="Data Ingest",
            description=f"{name}",
            quantity=f"{daily_val:,.1f} GB/day ({monthly_gb:,.0f} GB/mo)",
            unit_price=f"${NR_PRICING['data_per_gb_standard']}/GB",
            monthly_list=list_price,
            monthly_low=list_price * (1 - NR_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - NR_DISCOUNT_LOW),
        ))

    # Free tier credit (100 GB/month)
    if total_monthly > 0:
        free_credit = min(total_monthly, D(str(NR_PRICING["free_gb_per_month"]))) * NR_PRICING["data_per_gb_standard"]
        items.append(PricingLineItem(
            category="Credit",
            description="Free Tier (100 GB/month)",
            quantity="100 GB",
            unit_price="included",
            monthly_list=-free_credit,
            monthly_low=-free_credit,
            monthly_high=-free_credit,
        ))

    # User seats estimate (we don't have exact user count from screenshots)
    # Show range based on typical team sizes
    low_users_cost = D(str(NR_TYPICAL_USERS_LOW)) * NR_PRICING["full_platform_user"]
    high_users_cost = D(str(NR_TYPICAL_USERS_HIGH)) * NR_PRICING["full_platform_user"]
    items.append(PricingLineItem(
        category="Users",
        description=f"Full Platform Users (est. {NR_TYPICAL_USERS_LOW}–{NR_TYPICAL_USERS_HIGH})",
        quantity=f"{NR_TYPICAL_USERS_LOW}–{NR_TYPICAL_USERS_HIGH} users",
        unit_price=f"${NR_PRICING['full_platform_user']}/user/mo",
        monthly_list=high_users_cost,
        monthly_low=low_users_cost * (1 - NR_DISCOUNT_HIGH),
        monthly_high=high_users_cost * (1 - NR_DISCOUNT_LOW),
    ))

    # Totals
    est.total_list = sum(i.monthly_list for i in items)
    est.total_low = sum(i.monthly_low for i in items)
    est.total_high = sum(i.monthly_high for i in items)

    est.notes = [
        "Data ingest priced at $0.30/GB (Standard plan, on-demand).",
        "100 GB/month free tier deducted from total.",
        f"User seat estimate based on {NR_TYPICAL_USERS_LOW}–{NR_TYPICAL_USERS_HIGH} Full Platform users.",
        "Actual user count not available from Data Management screenshot.",
        "Low estimate assumes ~50% annual commitment discount.",
        "High estimate assumes ~20% annual commitment discount.",
        "Data Plus plan ($0.50/GB) adds enhanced security, compliance, and 90-day retention.",
    ]

    return est


# ---------------------------------------------------------------------------
# AWS CloudWatch pricing
# ---------------------------------------------------------------------------

CW_PRICING = {
    # Logs
    "put_log_events_per_gb": D("0.50"),          # $0.50/GB (standard regions)
    "timed_storage_per_gb_mo": D("0.028"),       # $0.028/GB-Mo log storage
    "s3_egress_per_gb": D("0.271"),              # $0.271/GB delivered to S3
    "log_insights_per_gb": D("0.0054"),          # $0.0054/GB scanned (5 GB free)
    "log_insights_free_gb": D("5"),              # 5 GB/month free

    # Metrics
    "metrics_first_10k_per_metric": D("0.30"),   # $0.30/metric-month (first 10K)
    "metrics_10k_250k_per_metric": D("0.10"),    # $0.10/metric-month (10K–250K)
    "metrics_250k_plus_per_metric": D("0.05"),   # $0.05/metric-month (250K+)
    "get_metric_data_per_1k": D("0.01"),         # $0.01/1K GetMetricData requests
    "put_metric_data_per_1k": D("0.01"),         # $0.01/1K PutMetricData requests
    "metric_update_per_1k": D("0.003"),          # $0.003/1K metric updates

    # Alarms
    "alarm_standard_per_month": D("0.10"),       # $0.10/alarm (standard resolution)
    "alarm_high_res_per_month": D("0.30"),       # $0.30/alarm (high-resolution)

    # X-Ray
    "xray_traces_per_million": D("0.50"),        # $0.50/million traces retrieved/scanned
    "xray_segments_per_million": D("0.50"),      # $0.50/million segments
}

# AWS doesn't negotiate like SaaS vendors, but there are Savings Plans / EDP
CW_DISCOUNT_LOW = D("0.05")    # 5% off (minimal commitment)
CW_DISCOUNT_HIGH = D("0.25")   # 25% off (large EDP / enterprise discount)


def _cw_tiered_metrics_cost(count: Decimal) -> Decimal:
    """Calculate tiered CloudWatch custom metrics cost."""
    cost = D("0")
    if count <= 0:
        return cost
    # First 10,000
    tier1 = min(count, D("10000"))
    cost += tier1 * CW_PRICING["metrics_first_10k_per_metric"]
    # 10,001 – 250,000
    if count > D("10000"):
        tier2 = min(count - D("10000"), D("240000"))
        cost += tier2 * CW_PRICING["metrics_10k_250k_per_metric"]
    # 250,001+
    if count > D("250000"):
        tier3 = count - D("250000")
        cost += tier3 * CW_PRICING["metrics_250k_plus_per_metric"]
    return cost


def estimate_cloudwatch(ext: CloudWatchExtraction) -> PricingEstimate:
    """Estimate AWS CloudWatch monthly spend from extracted billing data."""
    est = PricingEstimate(provider="cloudwatch")
    items = est.line_items

    # --- PutLogEvents (log ingestion) ---
    # Use ACTUAL cost from the bill when available (more accurate than recalculating,
    # since per-GB rate varies by region: $0.50 US, $0.54 EU, etc.)
    log_gb = ext.total_put_log_events_gb or 0
    actual_cost = ext.total_put_log_events_cost or 0
    if log_gb > 0 or actual_cost > 0:
        if actual_cost > 0:
            list_price = D(str(actual_cost))
            effective_rate = D(str(actual_cost)) / D(str(log_gb)) if log_gb > 0 else CW_PRICING["put_log_events_per_gb"]
            rate_str = f"${effective_rate.quantize(D('0.01'))}/GB (from bill)"
        else:
            list_price = D(str(log_gb)) * CW_PRICING["put_log_events_per_gb"]
            rate_str = f"${CW_PRICING['put_log_events_per_gb']}/GB"
        items.append(PricingLineItem(
            category="Logs",
            description="PutLogEvents (log ingestion)",
            quantity=f"{log_gb:,.1f} GB/mo",
            unit_price=rate_str,
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- Timed Storage ---
    storage = ext.total_timed_storage_gb_mo or 0
    if storage > 0:
        list_price = D(str(storage)) * CW_PRICING["timed_storage_per_gb_mo"]
        items.append(PricingLineItem(
            category="Logs",
            description="Log Storage (TimedStorage)",
            quantity=f"{storage:,.1f} GB-Mo",
            unit_price=f"${CW_PRICING['timed_storage_per_gb_mo']}/GB-Mo",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- S3 Egress ---
    s3_gb = ext.total_s3_egress_gb or 0
    if s3_gb > 0:
        list_price = D(str(s3_gb)) * CW_PRICING["s3_egress_per_gb"]
        items.append(PricingLineItem(
            category="Logs",
            description="S3 Egress (log delivery to S3)",
            quantity=f"{s3_gb:,.1f} GB",
            unit_price=f"${CW_PRICING['s3_egress_per_gb']}/GB",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- Log Insights ---
    insights_gb = ext.total_start_query_gb or 0
    if insights_gb > 0:
        billable_gb = max(D("0"), D(str(insights_gb)) - CW_PRICING["log_insights_free_gb"])
        list_price = billable_gb * CW_PRICING["log_insights_per_gb"]
        items.append(PricingLineItem(
            category="Logs",
            description="CloudWatch Logs Insights (5 GB free)",
            quantity=f"{insights_gb:,.1f} GB scanned",
            unit_price=f"${CW_PRICING['log_insights_per_gb']}/GB",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- Custom Metrics (tiered) ---
    metrics_count = ext.total_custom_metrics_count or 0
    if metrics_count > 0:
        list_price = _cw_tiered_metrics_cost(D(str(metrics_count)))
        items.append(PricingLineItem(
            category="Metrics",
            description="Custom Metrics (tiered pricing)",
            quantity=f"{metrics_count:,.0f} metrics",
            unit_price="$0.30/$0.10/$0.05 tiered",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- GetMetricData / PutMetricData API requests ---
    api_requests = ext.total_metric_api_requests or 0
    if api_requests > 0:
        thousands = D(str(api_requests)) / 1000
        list_price = thousands * CW_PRICING["get_metric_data_per_1k"]
        items.append(PricingLineItem(
            category="Metrics",
            description="GetMetricData/PutMetricData API",
            quantity=f"{api_requests:,.0f} requests",
            unit_price=f"${CW_PRICING['get_metric_data_per_1k']}/1K",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- Metric Updates ---
    updates = ext.total_metric_updates or 0
    if updates > 0:
        thousands = D(str(updates)) / 1000
        list_price = thousands * CW_PRICING["metric_update_per_1k"]
        items.append(PricingLineItem(
            category="Metrics",
            description="Metric Updates",
            quantity=f"{updates:,.0f} updates",
            unit_price=f"${CW_PRICING['metric_update_per_1k']}/1K",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- Alarms ---
    alarms = ext.total_alarms_count or 0
    if alarms > 0:
        list_price = D(str(alarms)) * CW_PRICING["alarm_standard_per_month"]
        items.append(PricingLineItem(
            category="Alarms",
            description="CloudWatch Alarms (standard resolution)",
            quantity=f"{alarms:,.0f} alarms",
            unit_price=f"${CW_PRICING['alarm_standard_per_month']}/alarm",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- X-Ray Traces ---
    traces = ext.total_xray_traces or 0
    if traces > 0:
        millions = D(str(traces)) / 1_000_000
        list_price = millions * CW_PRICING["xray_traces_per_million"]
        items.append(PricingLineItem(
            category="Traces",
            description="X-Ray Traces Recorded",
            quantity=f"{traces:,.0f} traces",
            unit_price=f"${CW_PRICING['xray_traces_per_million']}/M traces",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # --- X-Ray Segments ---
    segments = ext.total_xray_segments or 0
    if segments > 0:
        millions = D(str(segments)) / 1_000_000
        list_price = millions * CW_PRICING["xray_segments_per_million"]
        items.append(PricingLineItem(
            category="Traces",
            description="X-Ray Segments Recorded",
            quantity=f"{segments:,.0f} segments",
            unit_price=f"${CW_PRICING['xray_segments_per_million']}/M segments",
            monthly_list=list_price,
            monthly_low=list_price * (1 - CW_DISCOUNT_HIGH),
            monthly_high=list_price * (1 - CW_DISCOUNT_LOW),
        ))

    # Totals
    est.total_list = sum(i.monthly_list for i in items)
    est.total_low = sum(i.monthly_low for i in items)
    est.total_high = sum(i.monthly_high for i in items)

    est.notes = [
        "Log ingestion cost uses actual bill amount when available (region-specific rates).",
        "Custom Metrics use tiered pricing: $0.30 (first 10K), $0.10 (10K-250K), $0.05 (250K+).",
        "Log Insights: first 5 GB/month scanned is free.",
        "Actual costs may vary by region and AWS pricing agreement.",
    ]

    return est
