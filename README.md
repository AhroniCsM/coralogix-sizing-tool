# Coralogix Sizing Tool

Convert **Datadog** and **New Relic** billing screenshots into Coralogix sizing estimates — powered by GPT-4o Vision.

Upload a screenshot from a competitor's billing/usage page. The tool extracts values automatically, lets you review and correct them, then calculates GB/day per signal (Logs, Metrics, Traces, RUM) mapped to Coralogix's model. Also provides estimated competitor monthly spend (MRR/ARR).

## Live

**https://coralogix-sizing.web.app**

## Quick Start

### Option 1: Docker (recommended)

```bash
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY
docker compose up --build
```

Open http://localhost:8000

### Option 2: Local Python

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add your OPENAI_API_KEY
python run.py
```

Open http://localhost:8000

## How It Works

1. **Upload** — Select provider (Datadog or New Relic), drag & drop billing screenshots
2. **Extract** — GPT-4o Vision reads the screenshots and extracts all billing fields as structured data
3. **Review** — Editable form with confidence indicators (green/amber/red) — correct any mistakes
4. **Calculate** — Formulas convert competitor metrics to Coralogix sizing:
   - **Logs** GB/day
   - **Metrics** NumSeries
   - **Traces** GB/day
   - **RUM** sessions/day or GB/day
5. **Pricing** — Estimated competitor monthly spend with MRR/ARR breakdown
6. **Feedback** — Rate accuracy. Corrections are stored and used to improve future extractions

## Supported Providers

### Datadog
Upload the **Billable** tab from Plan & Usage. Optionally add the **Metrics Overview** screenshot for accurate NumSeries.

| What we extract | How we calculate |
|----------------|-----------------|
| Infra/APM Host Hours | `hours / 30 / 24 × 1.1` → host count |
| Ingested Logs (GB) | `÷ 30` → GB/day |
| Indexed Logs (all retentions) | Fallback: `count × 2.0 KB` |
| Custom Metrics | Added to NumSeries |
| Ingested/Indexed Spans | `÷ 30` → GB/day |
| RUM Sessions | `÷ 30.4` → sessions/day |

### New Relic
Upload the **Data Management** page showing "Avg daily ingest" per source.

| NR Source | CX Signal |
|-----------|-----------|
| Logging, Custom events, Serverless | Logs |
| Metrics, Infra Integrations/Hosts/Processes | Metrics |
| APM events, Tracing | Traces |
| Browser events, Mobile events | RUM |

## Features

- **Google OAuth** — Restricted to @coralogix.com emails
- **Per-user history** — Each user sees only their own past runs
- **Admin dashboard** — Audit log, usage stats, user management (`/admin`)
- **Competitor pricing** — Estimated DD/NR monthly spend with line-item breakdown
- **API cost tracking** — GPT-4o token usage and cost per extraction
- **Learning loop** — Feedback corrections improve future extractions

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o` | OpenAI model for vision extraction |
| `GOOGLE_CLIENT_ID` | (required) | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | (required) | Google OAuth client secret |
| `SESSION_SECRET` | `change-me` | Session encryption key |
| `PORT` | `8000` | Server port |
| `DEBUG` | `false` | Enable auto-reload for development |

## Development

```bash
# Run tests
pytest tests/ -v

# Run with hot reload
DEBUG=true python run.py
```

## Architecture

```
app/
├── config.py           # Settings from .env
├── database.py         # SQLite with WAL mode
├── models.py           # Pydantic extraction + result models
├── services/
│   ├── extractor.py    # GPT-4o Vision API integration
│   ├── datadog.py      # DD → CX calculation engine (Decimal math)
│   ├── newrelic.py     # NR → CX calculation engine (Decimal math)
│   ├── pricing.py      # Competitor pricing estimator
│   └── insights.py     # Feedback learning + CSV processing
├── routers/
│   ├── sizing.py       # Upload, extract, calculate
│   ├── feedback.py     # Accuracy feedback + insights
│   ├── admin.py        # Admin dashboard + user management
│   └── auth.py         # Google OAuth login/logout
└── templates/          # Jinja2 + Tailwind CSS
```

## Hosting

- **Cloud Run** — `me-west1` (Tel Aviv), min 1 instance
- **Firebase Hosting** — Proxies `coralogix-sizing.web.app` → Cloud Run
- **SQLite** — Embedded database in `/data/sizing.db`
