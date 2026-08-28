# 🤖 AI Job Agent (Autonomous 24/7 Career Automation)

> **Autonomous AI-powered job search and auto-apply agent** — scrapes 14 job sources (including ATS APIs and daily LinkedIn hiring posts), scores jobs with **Google Gemini 3.6 Flash** against your resume with strict 0–2 years experience filtering, generates tailored PDF resumes via ReportLab, auto-submits to ATS platforms (Greenhouse, Lever, Ashby), verifies and sends cold emails to verified HR inboxes via Gmail API, and runs automatically 24/7 every 6 hours.

---

## ⚡ Key Features

- **🌐 14 Multi-Tier Job Connectors**:
  - Direct ATS APIs (Greenhouse, Lever, Ashby) across 50+ tech companies.
  - **LinkedIn Hiring Posts Scraper** (`linkedin_posts`) for direct recruiter posts with email IDs.
  - **YCombinator / Hacker News** ("Who is Hiring" + Job Stories with contact email parser).
  - Aggregators: Adzuna (India), RemoteOK, Wellfound, WeWorkRemotely, Remotive, Himalayas, Naukri, Arbeitnow, Tier 5 Careers.
- **🧠 Google Gemini 3.6 Flash Scoring**:
  - Scores job descriptions (0–100) with detailed match breakdown and missing skills.
  - **Strict 0–2 Years Experience Target**: Excludes senior/lead/director roles (>2–3+ yrs) and focuses on Junior, Associate, Entry-Level, and Early Career Backend/Java/Python/AI positions.
- **📄 ATS Tailored PDF Resume Generation**:
  - Uses ReportLab to generate customized, ATS-compliant PDF resumes tailored to the matched job description.
- **📧 Smart Multi-TLD HR Email Discovery & Live DNS Validation**:
  - Prioritizes explicit recruiter emails extracted from JDs and LinkedIn posts.
  - Generates verified candidates: `hr@company.com`, `hr@company.in`, `hr@company.co`, `careers@...`, `talent@...`.
  - **DNS/MX Record Validation**: Tests recipient domains before queuing to ensure zero bounced emails.
- **📬 Automated Applications**:
  - Direct API submission for Greenhouse, Lever, and Ashby jobs.
  - Direct email outreach with resume attached via authenticated **Gmail OAuth2 API**.
- **⏰ 24/7 Fixed 6-Hour Cron Scheduler**:
  - Automatically triggers at **06:00 AM, 12:00 PM (Noon), 06:00 PM, and 12:00 AM (Midnight) IST**.
- **📊 Daily Excel Reporting**:
  - Produces formatted `.xlsx` reports detailing fetched jobs, scores, application statuses, and links.

---

## 🏗️ Architecture

```
                 APScheduler Cron (06:00, 12:00, 18:00, 00:00 IST)
                                      ↓
  ┌────────────────────────────────────────────────────────────────────────┐
  │                         LangGraph Pipeline                             │
  │                                                                        │
  │  1. Search ────► 2. Score ────► 3. Resume ────► 4. Apply / Outreach    │
  │      ↓                ↓              ↓                   ↓             │
  │  14 Connectors   Gemini Flash   Tailored PDF      • Direct ATS Form    │
  │  (ATS, Posts,    (0-2 Yrs)      (ReportLab)       • Gmail OAuth2 to HR │
  │   Aggregators)                                                         │
  │                                                                        │
  │  5. Notify ────► 6. Report ────► END                                   │
  │      ↓                ↓                                                │
  │   WhatsApp       Daily Excel                                           │
  │  (Cloud API)     JobReport.xlsx                                        │
  └────────────────────────────────────────────────────────────────────────┘
```

---

## 🔌 Job Sources (14 Active Connectors)

| Connector | Type | Method | Description |
|---|---|---|---|
| **`greenhouse`** | Direct ATS | REST API | 15+ tech companies (Anthropic, OpenAI, Stripe, Figma, GitLab...) |
| **`lever`** | Direct ATS | REST API | 15+ tech companies (Netflix, MongoDB, Vercel, Cloudflare, Postman...) |
| **`ashby`** | Direct ATS | REST API | 15+ tech companies (Linear, Retool, Brex, Ramp, Mistral AI, Hex...) |
| **`linkedin_posts`** | Social / Posts | Search Scraper | Recruiter hiring posts for 0-2 yrs with email IDs |
| **`ycombinator`** | Startups / HN | Firebase & Scrape | HN Job stories + monthly "Who is Hiring" threads |
| **`adzuna`** | Aggregator | REST API | India & Global tech jobs (Free API tier) |
| **`wellfound`** | Startups | GraphQL / API | AngelList tech startup postings |
| **`weworkremotely`** | Remote | RSS Feed | Remote developer & engineering roles |
| **`remotive`** | Remote | REST API | Curated software developer listings |
| **`arbeitnow`** | Tech Board | REST API | Tech & backend job feed |
| **`remoteok`** | Remote | REST API | Global remote software engineer jobs |
| **`himalayas`** | Remote | REST API | Tech & remote developer jobs |
| **`naukri`** | India Board | REST / Feed | India-focused tech postings |
| **`tier5_careers`** | Enterprise | Scrape / API | Direct enterprise career listings |

---

## 🚀 Quick Start

### 1. Clone & Set Up Python Environment
```bash
git clone https://github.com/kamalds2/AI-Job-Agent.git
cd AI-Job-Agent

# Create virtual environment (Python 3.11+)
python -m venv .venv
.\.venv\Scripts\activate   # On Windows
# source .venv/bin/activate # On Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Create a `.env` file with your credentials:
```ini
# LLM Provider (Primary: Gemini)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.6-flash

# Gmail OAuth2 (For sending cold outreach emails & tracking copies)
GMAIL_CLIENT_ID=your_oauth_client_id
GMAIL_CLIENT_SECRET=your_oauth_client_secret
GMAIL_REFRESH_TOKEN=your_refresh_token
EMAIL_ADDRESS=your_email@gmail.com

# Adzuna API (Optional, for India search)
ADZUNA_APP_ID=your_app_id
ADZUNA_APP_KEY=your_app_key

# Candidate Target Profile
CANDIDATE_NAME="Kamal Kumar"
CANDIDATE_PHONE="+91XXXXXXXXXX"
CANDIDATE_EXPERIENCE_YEARS="0-2 years"
```

### 3. Initialize Database
```bash
python scripts/setup_db.py
python scripts/check_system.py
```

### 4. Run the 24/7 Server or CLI Run
```bash
# Start 24/7 FastAPI Server with Background Scheduler:
uvicorn main:app --host 0.0.0.0 --port 8000

# OR trigger an on-demand full run via CLI:
python scripts/run_agent.py

# Test Gemini AI integration:
python scripts/test_gemini.py

# Refresh Gmail OAuth Token if needed:
python scripts/setup_gmail_token.py
```

---

## 🌐 API Reference (FastAPI)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Health check, scheduler status, next scheduled run time |
| `GET` | `/docs` | Interactive Swagger API documentation |
| `POST` | `/agent/run` | Trigger an immediate manual agent execution |
| `GET` | `/agent/status` | Current status of the agent pipeline and scheduler |
| `GET` | `/jobs/` | List all discovered jobs (filterable by source, remote, etc.) |
| `GET` | `/jobs/stats` | Aggregate database statistics (total, new, scored, qualified, applied) |
| `GET` | `/jobs/qualified` | List top-scoring jobs matching the experience and skill criteria |
| `GET` | `/applications/` | Application log history and delivery statuses |

---

## 📄 License
MIT License. Created by [Kamal Kumar](https://github.com/kamalds2).
