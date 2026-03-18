from decimal import Decimal
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Datadog extraction — all fields Optional, extracted from screenshots
# ---------------------------------------------------------------------------
class DatadogExtraction(BaseModel):
    # Hosts
    infra_hosts: float | None = None
    infra_hosts_is_hourly: bool = False
    apm_hosts: float | None = None
    apm_hosts_is_hourly: bool = False
    profiled_hosts: float | None = None
    profiled_hosts_is_hourly: bool = False
    network_hosts: float | None = None
    network_hosts_is_hourly: bool = False
    fargate_tasks: float | None = None

    # Containers
    container_hours: float | None = None
    profiled_containers: float | None = None
    profiled_containers_is_hourly: bool = False

    # Metrics
    custom_metrics: float | None = None
    custom_metrics_is_hourly: bool = False

    # Logs — indexed counts in MILLIONS
    indexed_logs_3d: float | None = None
    indexed_logs_7d: float | None = None
    indexed_logs_15d: float | None = None
    indexed_logs_live: float | None = None
    indexed_logs_90d: float | None = None
    # Logs — ingested in GB
    ingested_logs_gb: float | None = None
    analyzed_logs_security_gb: float | None = None

    # Spans
    ingested_spans_gb: float | None = None
    indexed_spans_million: float | None = None
    custom_events: float | None = None

    # Serverless
    serverless_functions: float | None = None
    serverless_invocations: float | None = None

    # RUM
    rum_sessions: float | None = None
    error_tracking_events: float | None = None

    # From Metrics Overview screenshot
    total_metrics_from_overview: float | None = None

    # Metadata
    missing_fields: list[str] = []
    confidence: dict[str, str] = {}  # field -> "high" | "medium" | "low"


# ---------------------------------------------------------------------------
# New Relic extraction — Avg daily ingest GB per source
# ---------------------------------------------------------------------------
class NewRelicExtraction(BaseModel):
    # Logs sources
    logging_gb_day: float | None = None
    custom_events_gb_day: float | None = None
    serverless_gb_day: float | None = None
    security_bytes_gb_day: float | None = None

    # Metrics sources
    metrics_gb_day: float | None = None
    infra_integrations_gb_day: float | None = None
    infra_hosts_gb_day: float | None = None
    infra_processes_gb_day: float | None = None

    # Traces sources
    apm_events_gb_day: float | None = None
    tracing_gb_day: float | None = None

    # RUM sources
    browser_events_gb_day: float | None = None
    mobile_events_gb_day: float | None = None

    # Metadata
    missing_fields: list[str] = []
    confidence: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Sizing result — the final output
# ---------------------------------------------------------------------------
class SizingResult(BaseModel):
    provider: str
    logs_gb_day: Decimal
    metrics_num_series: int
    metrics_gb_day: Decimal  # for display
    traces_gb_day: Decimal
    rum_gb_day: Decimal = Decimal("0")
    rum_sessions_day: int | None = None
    warnings: list[str] = []
    details: dict = {}  # provider-specific intermediate values
