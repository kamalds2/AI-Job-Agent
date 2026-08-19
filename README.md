# 🤖 AI Job Agent

> **Autonomous AI-powered job search agent** — searches 9 job sources, scores jobs with Claude AI against your resume, generates tailored PDFs, drafts cold emails, sends WhatsApp alerts, and runs automatically every 6 hours.

---

## Architecture

```
Scheduler (every 6h)
        ↓
  ┌─────────────────────────────────────────────────────────┐
  │                   LangGraph Pipeline                     │
  │                                                         │
  │  1. Search ──► 2. Score ──► 3. Resume ──► 4. Email     │
  │      ↓              ↓            ↓             ↓        │
  │  9 Sources     Claude AI    PDF via       Gmail API     │
  │                             ReportLab                   │
  │                                                         │
  │  5. Notify ──► 6. Report ──► END                        │
  │      ↓              ↓                                   │
  │  WhatsApp       Excel .xlsx                             │
  └─────────────────────────────────────────────────────────┘
```

## Job Sources (9 Connectors)

| Tier | Source | Method | Jobs/Run |
|------|--------|--------|----------|
| 1 | RemoteOK | Public API | ~100 |
| 1 | Wellfound | GraphQL API | ~50 |
| 1 | YCombinator | API + Scrape | ~30 |
| 2 | **Greenhouse** (15+ companies) | ATS API | ~800 |
| 2 | **Lever** (15+ companies) | ATS API | ~200 |
| 2 | **Ashby** (15+ companies) | ATS API | ~240 |
| 3 | WeWorkRemotely | RSS Feed | ~200 |
| 3 | Remotive | Public API | ~50 |
| 3 | Himalayas | Public API | ~50 |

**Greenhouse companies:** Anthropic, OpenAI, Stripe, Airbnb, DoorDash, Plaid, Gusto, HashiCorp, GitLab, Figma, Notion, Confluent, Twilio, Datadog, Segment

**Lever companies:** Netflix, Shopify, Atlassian, Dropbox, Reddit, GitHub, Elastic, MongoDB, Grafana, Sentry, Vercel, Cloudflare, Razorpay, Postman

**Ashby companies:** Linear, Retool, Rippling, Ramp, Brex, Scale AI, Cohere, Mistral AI, Runway, Replit, dbt Labs, Airbyte, Prefect, Modal Labs, Baseten

---

## Quick Start

### 1. Install Dependencies
```bash
cd c:\kamal\AI-Job-Agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure `.env`
```bash
# Edit .env and add your keys:
ANTHROPIC_API_KEY=sk-ant-...       # Required for AI scoring
EMAIL_ADDRESS=your@gmail.com       # For email drafting
GMAIL_REFRESH_TOKEN=...            # For sending emails (optional)
WHATSAPP_TOKEN=...                 # For WhatsApp alerts (optional)
```

### 3. Set Up Database
```bash
python scripts/setup_db.py
```

### 4. Run the Agent
```bash
# Start the server (auto-runs every 6 hours)
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# OR run manually via CLI
python scripts/run_agent.py              # Full run
python scripts/run_agent.py --dry-run   # Test (no emails sent)
python scripts/run_agent.py --search-only  # Just fetch jobs
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Health check + scheduler status |
| GET | `/docs` | Swagger UI |
| POST | `/agent/run` | Trigger agent manually |
| GET | `/agent/status` | Current agent + scheduler status |
| GET | `/jobs/` | All jobs (filterable) |
| GET | `/jobs/stats` | Total, new, applied, qualified counts |
| GET | `/jobs/qualified` | Jobs above score threshold |
| GET | `/applications/` | All applications |
| GET | `/applications/stats` | Application statistics |

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | **Required** — Claude API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-5` | Model to use |
| `MATCH_SCORE_THRESHOLD` | `65` | Min score to qualify (0-100) |
| `MAX_APPLICATIONS_PER_RUN` | `10` | Max emails per run |
| `SCHEDULER_INTERVAL_HOURS` | `6` | How often to run |
| `DRY_RUN` | `false` | Set `true` to disable sending |
| `DATABASE_URL` | `sqlite:///job_agent.db` | Database URL |

---

## Gmail OAuth2 Setup (for sending emails)

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create project → Enable Gmail API
3. Create OAuth2 credentials (Desktop App)
4. Download `credentials.json`
5. Run: `python scripts/gmail_oauth.py` (generates refresh token)
6. Add `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN` to `.env`

## WhatsApp Setup

1. Go to [Meta for Developers](https://developers.facebook.com)
2. Create App → Add WhatsApp product
3. Get `Access Token` and `Phone Number ID`
4. Add to `.env` as `WHATSAPP_TOKEN` and `WHATSAPP_PHONE_ID`
5. Set `WHATSAPP_TO_NUMBER` to your number (e.g., `919XXXXXXXXXX`)

---

## File Structure

```
AI-Job-Agent/
├── main.py                          # FastAPI app + scheduler startup
├── .env                             # Configuration (copy from .env template)
├── requirements.txt
│
├── app/
│   ├── agents/
│   │   ├── state.py                 # LangGraph AgentState schema
│   │   ├── nodes.py                 # All 6 pipeline node implementations
│   │   └── orchestrator.py          # Graph builder + run_agent()
│   │
│   ├── connectors/
│   │   ├── base_connector.py        # Abstract base class
│   │   ├── registry.py              # @register_connector decorator
│   │   ├── manager.py               # Runs all connectors concurrently
│   │   ├── remoteok_connector.py
│   │   ├── wellfound_connector.py
│   │   ├── yc_connector.py
│   │   ├── greenhouse_connector.py  # 15 companies
│   │   ├── lever_connector.py       # 15 companies
│   │   ├── ashby_connector.py       # 15 companies
│   │   ├── weworkremotely_connector.py
│   │   ├── remotive_connector.py
│   │   └── himalayas_connector.py
│   │
│   ├── services/
│   │   ├── scoring_service.py       # Claude AI job scoring
│   │   ├── resume_service.py        # PDF resume generation
│   │   ├── email_service.py         # Gmail OAuth2 email sending
│   │   ├── whatsapp_service.py      # WhatsApp alerts
│   │   ├── report_service.py        # Excel report generation
│   │   └── scheduler_service.py     # APScheduler (every 6h)
│   │
│   ├── api/
│   │   ├── jobs.py                  # Jobs CRUD + stats
│   │   ├── agent.py                 # Agent control endpoints
│   │   └── applications.py          # Applications tracking
│   │
│   ├── prompts/
│   │   ├── scoring_prompt.py        # Job scoring prompt
│   │   ├── resume_prompt.py         # Resume tailoring prompt
│   │   └── email_prompt.py          # Email drafting prompt
│   │
│   ├── models/                      # SQLAlchemy ORM models
│   ├── repositories/                # Database CRUD operations
│   └── config/settings.py           # All configuration
│
├── resumes/
│   └── Kamal_Kumar_Java_AI_Developer_ATS.pdf   # Master resume
│
├── reports/                         # Auto-generated Excel reports
├── scripts/
│   ├── run_agent.py                 # CLI runner
│   └── setup_db.py                  # DB initialization
```

---

## Adding More Companies

### Greenhouse
Edit `app/connectors/greenhouse_connector.py`, add to `GREENHOUSE_COMPANIES`:
```python
{"token": "company-token", "name": "Company Name"},
```
Find the token from `https://boards.greenhouse.io/{token}/jobs`

### Lever
Edit `app/connectors/lever_connector.py`, add to `LEVER_COMPANIES`:
```python
{"token": "company-slug", "name": "Company Name"},
```

### Ashby
Edit `app/connectors/ashby_connector.py`, add to `ASHBY_COMPANIES`:
```python
{"token": "company-slug", "name": "Company Name"},
```

---

## Customizing Scoring

Edit `app/prompts/scoring_prompt.py` to adjust:
- Target skills (Java, Spring Boot, Python, AWS, etc.)
- Experience range
- Preferred job types (remote, hybrid)
- Geographic preferences (India, USA, remote)

The default is optimized for: **Java/Spring Boot Backend + AWS/Cloud + AI/ML upskilling**
