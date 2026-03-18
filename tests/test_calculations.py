"""Tests for Datadog and New Relic sizing calculations.

Reference values from real SE spreadsheets (Tango, BigId).
"""

from decimal import Decimal

import pytest

from app.models import DatadogExtraction, NewRelicExtraction
from app.services.datadog import calculate as dd_calculate
from app.services.newrelic import calculate as nr_calculate

D = Decimal


class TestDatadogHourlyConversion:
    """Verify hourly → count conversion: hours / 30 / 24 * 1.1"""

    def test_infra_hosts_hourly(self):
        ext = DatadogExtraction(
            infra_hosts=469_000,
            infra_hosts_is_hourly=True,
        )
        result = dd_calculate(ext)
        # 469000 / 30 / 24 * 1.1 ≈ 716.5 → rounds to 717
        assert int(D(result.details["infra_hosts"])) == 717

    def test_apm_hosts_hourly(self):
        ext = DatadogExtraction(
            apm_hosts=144_000,
            apm_hosts_is_hourly=True,
        )
        result = dd_calculate(ext)
        # 144000 / 30 / 24 * 1.1 ≈ 220
        assert int(D(result.details["apm_hosts"])) == 220

    def test_non_hourly_passthrough(self):
        ext = DatadogExtraction(infra_hosts=500, infra_hosts_is_hourly=False)
        result = dd_calculate(ext)
        assert result.details["infra_hosts"] == "500"


class TestDatadogLogs:
    def test_ingested_logs(self):
        ext = DatadogExtraction(ingested_logs_gb=52_000)
        result = dd_calculate(ext)
        # 52000 / 30 ≈ 1733.33
        assert result.logs_gb_day == D("1733.33")

    def test_indexed_fallback(self):
        """When ingested logs missing, fall back to indexed × avg size."""
        ext = DatadogExtraction(
            indexed_logs_3d=20_800,  # 20.8B = 20800M
            indexed_logs_7d=0,
            indexed_logs_15d=0,
        )
        result = dd_calculate(ext)
        assert result.logs_gb_day > 0
        assert any("FALLBACK" in w for w in result.warnings)

    def test_no_logs_warning(self):
        ext = DatadogExtraction()
        result = dd_calculate(ext)
        assert any("MISSING" in w and "log" in w.lower() for w in result.warnings)


class TestDatadogMetrics:
    def test_metrics_from_overview_is_reference_only(self):
        """Metrics Overview is stored as reference, NOT used as primary value."""
        ext = DatadogExtraction(
            total_metrics_from_overview=7_070_000,
            infra_hosts=500,
        )
        result = dd_calculate(ext)
        # Should use calculated: 500 × 750 = 375,000 — NOT 7.07M
        assert result.metrics_num_series == 375_000
        assert result.details.get("metrics_overview_reference") == "7070000"

    def test_metrics_calculated(self):
        ext = DatadogExtraction(
            infra_hosts=500,
            infra_hosts_is_hourly=False,
            custom_metrics=100_000,
        )
        result = dd_calculate(ext)
        # (500 + 0) × 750 + 0 + 100000 = 475000
        assert result.metrics_num_series == 475_000

    def test_metrics_discrepancy_warning(self):
        """Big gap between Overview and calculated triggers a NOTE warning."""
        ext = DatadogExtraction(
            total_metrics_from_overview=10_000_000,
            infra_hosts=10,  # calculated: 10 × 750 = 7,500
        )
        result = dd_calculate(ext)
        assert result.metrics_num_series == 7_500  # calculated, not 10M
        assert any("NOTE" in w for w in result.warnings)


class TestDatadogTraces:
    def test_ingested_spans(self):
        ext = DatadogExtraction(ingested_spans_gb=67_000)  # 67TB converted to GB
        result = dd_calculate(ext)
        # 67000 / 30 ≈ 2233.33
        assert result.traces_gb_day == D("2233.33")

    def test_indexed_fallback(self):
        ext = DatadogExtraction(indexed_spans_million=500)
        result = dd_calculate(ext)
        assert result.traces_gb_day > 0
        assert any("FALLBACK" in w for w in result.warnings)


class TestDatadogRUM:
    def test_rum_sessions(self):
        ext = DatadogExtraction(rum_sessions=1_000_000, error_tracking_events=50_000)
        result = dd_calculate(ext)
        assert result.rum_sessions_day is not None
        assert result.rum_sessions_day > 0

    def test_no_rum_warning(self):
        ext = DatadogExtraction()
        result = dd_calculate(ext)
        assert any("RUM" in w for w in result.warnings)


class TestNewRelicLogs:
    def test_logs_sum(self):
        ext = NewRelicExtraction(
            logging_gb_day=100.0,
            custom_events_gb_day=20.0,
            serverless_gb_day=5.0,
            security_bytes_gb_day=2.0,
        )
        result = nr_calculate(ext)
        assert result.logs_gb_day == D("127.00")

    def test_missing_logging_warning(self):
        ext = NewRelicExtraction()
        result = nr_calculate(ext)
        assert any("Logging" in w for w in result.warnings)


class TestNewRelicMetrics:
    def test_metrics_num_series(self):
        ext = NewRelicExtraction(
            metrics_gb_day=50.0,
            infra_integrations_gb_day=30.0,
            infra_hosts_gb_day=20.0,
            infra_processes_gb_day=10.0,
        )
        result = nr_calculate(ext)
        # total = 110 GB/day → 110 × 1000 = 110000 NumSeries
        assert result.metrics_num_series == 110_000


class TestNewRelicTraces:
    def test_traces_sum(self):
        ext = NewRelicExtraction(
            apm_events_gb_day=80.0,
            tracing_gb_day=40.0,
        )
        result = nr_calculate(ext)
        assert result.traces_gb_day == D("120.00")


class TestNewRelicRUM:
    def test_rum_sum(self):
        ext = NewRelicExtraction(
            browser_events_gb_day=5.0,
            mobile_events_gb_day=2.0,
        )
        result = nr_calculate(ext)
        assert result.rum_gb_day == D("7.00")


class TestTangoReference:
    """Validate against Tango spreadsheet known outputs."""

    def test_tango_logs(self):
        """Tango: Ingested Logs 52,000 GB/month → 1,733 GB/day."""
        ext = DatadogExtraction(ingested_logs_gb=52_000)
        result = dd_calculate(ext)
        assert result.logs_gb_day == D("1733.33")

    def test_tango_traces(self):
        """Tango: Ingested Spans 66.7 TB = 66,700 GB → 2,223 GB/day."""
        ext = DatadogExtraction(ingested_spans_gb=66_700)
        result = dd_calculate(ext)
        assert result.traces_gb_day == D("2223.33")


class TestTrigoReference:
    """Validate against Trigo DD Sizing CSV."""

    def test_trigo_logs_with_security(self):
        """Trigo: Ingested 5,560 + Security 3,270 = 8,830 → 294.33 GB/day."""
        ext = DatadogExtraction(
            ingested_logs_gb=5560,
            analyzed_logs_security_gb=3270,
        )
        result = dd_calculate(ext)
        assert result.logs_gb_day == D("294.33")

    def test_trigo_metrics_uses_calculated_not_overview(self):
        """Trigo: calculated=1,668,042. Metrics Overview 4.09M must NOT override."""
        ext = DatadogExtraction(
            infra_hosts=249,
            apm_hosts=77,
            network_hosts=25,
            container_hours=1_080_000,  # always hourly, converted internally
            custom_metrics=167_000,
            total_metrics_from_overview=4_090_000,
        )
        result = dd_calculate(ext)
        # Must use calculated, not the 4.09M overview
        assert result.metrics_num_series < 2_000_000
        assert "NOTE" in " ".join(result.warnings)

    def test_trigo_traces(self):
        """Trigo: 9,640 GB/month → 321.33 GB/day."""
        ext = DatadogExtraction(ingested_spans_gb=9640)
        result = dd_calculate(ext)
        assert result.traces_gb_day == D("321.33")

    def test_metrics_overview_discrepancy_warning(self):
        """When overview differs >2x from calculated, emit a warning."""
        ext = DatadogExtraction(
            infra_hosts=100,
            custom_metrics=50_000,
            total_metrics_from_overview=5_000_000,
        )
        result = dd_calculate(ext)
        # Should use calculated (100*750 + 50000 = 125000), NOT 5M
        assert result.metrics_num_series == 125_000
        assert any("NOTE" in w for w in result.warnings)
