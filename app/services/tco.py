"""Coralogix TCO Optimizer pricing constants.

Mirrors the internal "TCO Optimizer - Playground" spreadsheet.
Each signal type has tiers with cost-optimization percentages and per-GB pricing.
"""

# Coralogix pricing per signal type and tier
CX_PRICING = {
    "logs": {
        "compliance": {
            "label": "Compliance",
            "features": "Direct Object Storage queries\nLive-tail\nError spike anomalies",
            "use_case": "Provides direct queries of logs with full analytics capabilities using Dataprime.",
            "cost_opt": 0.88,
            "price_per_gb": 0.102,
            "default_pct": 0.10,
            "gb_per_unit": 8.33,
        },
        "monitoring": {
            "label": "Monitoring",
            "features": "+ Alerting\nLoggregation (ML-clustering)\nFlow anomalies\nCustom Dashboards",
            "use_case": "Define alerts, error tracking and dashboards, along with direct object storage querying and full analytics.",
            "cost_opt": 0.68,
            "price_per_gb": 0.272,
            "default_pct": 0.70,
            "gb_per_unit": 3.13,
        },
        "frequent_search": {
            "label": "Frequent Search",
            "features": "+ Lightning-fast Queries\nDashboards",
            "use_case": "Most important logs stored on highly available SSDs, replicated, ready to query within seconds.",
            "cost_opt": 0.20,
            "price_per_gb": 0.680,
            "default_pct": 0.20,
            "gb_per_unit": 1.25,
        },
    },
    "metrics": {
        "metrics": {
            "label": "Metrics",
            "features": "Store in Object Storage, queries, alerting, dashboards",
            "use_case": "Collect all metric data including infrastructure, network, security, and application metrics.",
            "cost_opt": 0.97,
            "price_per_gb": 0.028,
            "gb_per_unit": 30.00,
        },
    },
    "tracing": {
        "compliance": {
            "label": "Compliance",
            "features": "Direct Object Storage queries",
            "use_case": "Provides direct queries of traces with full analytics capabilities using Dataprime.",
            "cost_opt": 0.90,
            "price_per_gb": 0.085,
            "default_pct": 1.0,
            "gb_per_unit": 10.00,
        },
        "monitoring": {
            "label": "Monitoring",
            "features": "+ Error Tracking\nAlerting\nService Catalog\nService map",
            "use_case": "Define alerts, error tracking and dashboards, along with direct object storage querying.",
            "cost_opt": 0.75,
            "price_per_gb": 0.213,
            "default_pct": 0.0,
            "gb_per_unit": 4.00,
        },
        "frequent_search": {
            "label": "Frequent Search",
            "features": "+ Lightning-fast queries\nDashboards",
            "use_case": "Traces available for alerts, dashboards, archival, and lightning-fast querying.",
            "cost_opt": 0.50,
            "price_per_gb": 0.425,
            "default_pct": 0.0,
            "gb_per_unit": 2.00,
        },
    },
    "rum": {
        "compliance": {
            "label": "Compliance",
            "features": "Direct Object Storage queries\nLive-tail\nError spike anomalies",
            "use_case": "Non-critical front-end data kept for compliance/post-processing, straight to object storage.",
            "cost_opt": 0.88,
            "price_per_gb": 0.102,
            "default_pct": 0.0,
            "gb_per_unit": 8.33,
        },
        "monitoring": {
            "label": "Monitoring",
            "features": "+ Alerting\nLoggregation (ML-clustering)\nFlow anomalies\nCustom Dashboards",
            "use_case": "Front-end data for monitoring: alerts, dashboards, statistics, live data stream, proactive anomalies.",
            "cost_opt": 0.68,
            "price_per_gb": 0.272,
            "default_pct": 1.0,
            "gb_per_unit": 3.13,
        },
        "frequent_search": {
            "label": "Frequent Search",
            "features": "+ Lightning-fast Queries\nDashboards",
            "use_case": "Most important front-end data on highly available SSDs, replicated, ready to query within seconds.",
            "cost_opt": 0.20,
            "price_per_gb": 0.680,
            "default_pct": 0.0,
            "gb_per_unit": 1.25,
        },
    },
}

# Default settings
DEFAULTS = {
    "logs_retention_days": 7,
    "metrics_scrape_interval_sec": 60,
    "storage_retention": "Unlimited",
}
