# Coralogix Sizing Tool

Convert **Datadog** and **New Relic** billing screenshots into Coralogix sizing estimates — powered by Claude Vision.

Upload a screenshot from a competitor's billing/usage page. The tool extracts values automatically, lets you review and correct them, then calculates GB/day per signal (Logs, Metrics, Traces, RUM) mapped to Coralogix's model.

## Quick Start

### Option 1: Docker (recommended)

```bash
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY
docker compose up --build
```

Open http://localhost:8000

### Option 2: Local Python

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add your ANTHROPIC_API_KEY
python run.py
```

Open http://localhost:8000

## How It Works

1. **Upload** — Select provider (Datadog or New Relic), drag & drop billing screenshots
2. **Extract** — Claude Vision reads the screenshots and extracts all billing fields as structured data
3. **Review** — Editable form with confidence indicators (green/amber/red) — correct any mistakes
4. **Calculate** — Formulas convert competitor metrics to Coralogix sizing:
   - **Logs** GB/day
   - **Metrics** NumSeries
   - **Traces** GB/day
   - **RUM** sessions/day or GB/day
5. **Feedback** — Rate accuracy. Corrections are stored and used to improve future extractions

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

## Learning from CSVs

Drop `.csv` files into `data/screenshots/datadog/` or `data/screenshots/newrelic/`. The tool learns field patterns from them on startup and via the "Re-learn from CSVs" button on `/insights`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | (required) | Your Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model for vision extraction |
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
│   ├── extractor.py    # Claude Vision API integration
│   ├── datadog.py      # DD → CX calculation engine (Decimal math)
│   ├── newrelic.py     # NR → CX calculation engine (Decimal math)
│   └── insights.py     # Feedback learning + CSV processing
├── routers/
│   ├── sizing.py       # Upload, extract, calculate
│   └── feedback.py     # Accuracy feedback + insights
└── templates/          # Jinja2 + Tailwind CSS
```
