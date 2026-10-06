# 🌐 Autonomous Multi-Agent Job Application System: Comprehensive Architectural Blueprint & Engineering Specification

> **Purpose:** This blueprint defines the complete, production-grade architecture, rule set, and step-by-step implementation guide to build autonomous multi-agent job application systems for any candidate profile (Tech, Finance, Data Science, Product, etc.).

---

## 🏛️ 1. High-Level Multi-Agent Architecture

The system executes in a **3-Phase Sequential Multi-Agent Workflow** using **Google Gemini** as the primary intelligence and reasoning engine across all components.

```mermaid
flowchart TD
    Start([System Trigger / 24-7 Cron Scheduler]) --> P1[Phase 1: ATS & Job Boards Aggregator Agent]
    
    subgraph Phase 1: API Aggregation & Reporting
        P1 --> S1[Query Job APIs: RemoteOK, Greenhouse, Lever, Ashby, Himalayas]
        S1 --> S2[Gemini AI Profile Match Scoring >= Threshold]
        S2 --> S3[Generate Tailored 1-Page ATS PDF Resumes in resumes/aggregator/]
        S3 --> S4[Draft Cold Emails & Dispatch WhatsApp Notifications]
        S4 --> S5[Generate Structured Excel Report in reports/]
    end

    S5 --> P2[Phase 2: LinkedIn Recruiter Feed & Outreach Agent]

    subgraph Phase 2: Recruiter Outreach
        P2 --> R1[Scan Live LinkedIn Recruiter & HR Posts]
        R1 --> R2[Gemini extracts verified HR Emails & Role Requirements]
        R2 --> R3[Dispatch Cold Email with Tailored PDF Attached]
        R3 --> R4[Generate Dedicated HR Outreach Report]
    end

    R4 --> P3[Phase 3: Sequential Multi-Board Browser Auto-Apply Agents]

    subgraph Phase 3: Browser Auto-Apply Pipeline (Max 40-50 Apps / Portal)
        P3 --> B1[1. LinkedIn Browser Agent: Auto-Apply 40-50 Jobs]
        B1 -->|40-50 Done / Limit / No more jobs| B2[2. Indeed Browser Agent: Auto-Apply 40-50 Jobs]
        B2 -->|40-50 Done / No more jobs| B3[3. Y Combinator Browser Agent: Auto-Apply 40-50 Jobs]
        B3 -->|40-50 Done / No more jobs| B4[4. Hirist Browser Agent: Auto-Apply 40-50 Jobs]
        B4 -->|40-50 Done / No more jobs| B5[5. Cutshort Browser Agent: Auto-Apply 40-50 Jobs]
    end

    B5 --> Summary([Final Consolidated Summary, Notifications & Metrics])
```

---

## 🔧 2. Core Browser Automation Architecture (CDP Protocol)

### 2.1 Single Shared Browser Instance
All browser agents **MUST** connect to the **same live Google Chrome instance** via Chrome DevTools Protocol (`CDP_PORT = 9222`) rather than creating isolated browser sandboxes.

- **Port:** `9222` (`http://127.0.0.1:9222`)
- **User Data Dir:** `%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile` (preserves active sessions, logins, cookies, 2FA, and localStorage).
- **Zero Credentials Policy:** The agent reuses existing authenticated tabs for LinkedIn, Cutshort, Hirist, Indeed, and YC.
- **Application Target Cap:** Each portal agent targets **40 to 50 applications** (or advances earlier if daily limits/jobs are exhausted) before automatically switching to the next browser agent.

### 2.2 Connection Protocol Standard
```python
async def connect(self, context=None, page=None):
    if context and page:
        self._context = context
        self._page = page
        return

    self._playwright = await async_playwright().start()
    if not self.is_cdp_port_open():
        self._launch_native_chrome()
        for _ in range(12):
            await asyncio.sleep(1.0)
            if self.is_cdp_port_open():
                break

    self._browser = await self._playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")
    contexts = self._browser.contexts
    self._context = contexts[0] if contexts else await self._browser.new_context()
    pages = self._context.pages
    self._page = pages[0] if pages else await self._context.new_page()
```

---

## 🎯 3. Multi-Portal Browser Agents: Step-by-Step Execution Specs

### 🔵 Portal 1: LinkedIn Browser Auto-Apply Agent
* **Target:** Easy Apply listings within the past 24 hours (`f_TPR=r86400`), sorted by most recent (`sortBy=DD`) (max 40-50 applications per session).
* **Multi-Role Sweep:** Iterates through primary and adjacent role keywords (e.g., *Java Backend Developer $\rightarrow$ Spring Boot Developer $\rightarrow$ Full Stack Developer*).
* **Step-by-Step Flow:**
  1. Navigate to `https://www.linkedin.com/jobs/search/?keywords=<encoded_role>&location=<location>&f_TPR=r86400&f_AL=true&sortBy=DD`.
  2. Verify login state (check `.global-nav__me`).
  3. Extract all job cards on current page (up to 25 per page).
  4. For each card:
     - Check title/description against experience filter (e.g., skip `Senior`, `Lead`, `VP`, `>3 Years`).
     - Check `JobTracker` database to skip already-applied jobs.
     - Check for daily limit banner (`We limit daily submissions...`); if present, immediately exit LinkedIn and advance to Indeed.
     - Click card to expand full JD body.
     - Dynamically generate a 1-page tailored ATS PDF resume in `resumes/linkedin/`.
     - Click `Easy Apply` button.
     - **Form Self-Healer:** Fill multi-step modals (Text inputs, radio buttons, dropdown selects, work authorization, checkboxes) using Gemini reasoning with fallback heuristics. Notice period is answered as numerical `"0"`.
     - Upload tailored PDF resume.
     - Submit application or record dry-run preview screenshot.
  5. If 40-50 applications reached, or daily limit/jobs exhausted, advance immediately to Indeed.

---

### 🟢 Portal 2: Indeed Browser Auto-Apply Agent
* **Target:** Jobs with `Easily apply` tag within last 24 hours (`fromage=1`, max 40-50 applications per session).
* **Step-by-Step Flow:**
  1. Navigate to `https://in.indeed.com/jobs?q=<encoded_role>&l=<location>&fromage=1`.
  2. Extract job cards (`div.job_seen_beacon`, `td.resultContent`).
  3. Filter out non-matching experience levels.
  4. Click `Easily apply` / `Apply now` button:
     - If opens in new tab, switch context to active page.
     - Navigate through Indeed smart-apply multi-step container.
     - Attach tailored PDF from `resumes/indeed/`.
     - Answer screening questions (Years of experience, notice period as numeric `"0"`, location, salary expectations) via Gemini form filler.
     - Advance through steps to the final Review stage.
     - **Submit Application Guarantee:** Locate and click the final `Submit your application` / `Submit` button.
     - **On-Screen Confirmation Verification:** Wait up to 15 seconds to verify on-screen success messages (`Your application has been submitted`, `Application submitted`, `Application sent`).
     - Only after the successful submission message is verified, safely close the popup tab and return focus to apply for the next role.
  5. Once 40-50 applications are submitted or listings are exhausted, advance to Y Combinator.

---

### 🟠 Portal 3: Y Combinator (Work at a Startup) Auto-Apply Agent
* **Target:** Early-stage & growth YC startups hiring in candidate domain.
* **Step-by-Step Flow:**
  1. Navigate to `https://www.workatastartup.com/jobs`.
  2. Verify session (`div.user-menu` or profile icon).
  3. Apply domain/role filter and experience filter.
  4. For each startup job card:
     - Read full role requirements and founder/company summary.
     - Generate ATS tailored resume in `resumes/ycombinator/`.
     - Click `Apply` button to trigger application modal.
     - Draft a high-impact founder pitch highlighting relevant achievements and immediate availability.
     - Type pitch message with human typing cadences (`_human_type`).
     - Attach tailored resume & submit.

---

### 🟣 Portal 4: Hirist Browser Auto-Apply Agent
* **Target:** Active feed listings on Hirist (`https://www.hirist.tech/jobfeed` or `hirist.com`).
* **Step-by-Step Flow:**
  1. Navigate to `HIRIST_FEED_URL`.
  2. Verify authenticated feed state.
  3. Scan all visible job listing cards across feed viewport.
  4. For each eligible job:
     - Open job in background tab (`middle-click` or `new_page`).
     - Read expanded JD and company details.
     - Generate 1-page ATS PDF in `resumes/hirist/`.
     - Click primary `Apply` / `Apply Now` button.
     - Handle confirmation modal and attach tailored resume if file input is present.
     - Record application and close job tab.
  5. If cards exhausted and target not met: Scroll down (up to 3 attempts) to trigger infinite feed loading. If no more jobs, advance to Cutshort.

---

### 💜 Portal 5: Cutshort Browser Auto-Apply Agent
* **Target:** Matched profile jobs (`https://cutshort.io/profile/all-jobs?minexp=0&maxexp=2&hiringActivityOnJob=1-days`).
* **Step-by-Step Flow:**
  1. Navigate to Cutshort jobs feed with pre-set filters.
  2. Ensure **Profile matcher is ON**.
  3. Expand JD via `Read more` button and extract exact required skills.
  4. Click `Apply now` on card to open Cutshort application modal.
  5. Extract authoritative Title, Company, and Recruiter Name from modal header.
  6. Generate tailored ATS PDF in `resumes/cutshort/` (e.g. `Resume_Kamal_Kumar_<tag>.pdf`).
  7. Copy to clean standard filename (`Kamal_Kumar_Resume.pdf`) to satisfy Cutshort S3 `signedUrl` filename validator.
  8. **Robust Resume Uploading**:
     - Launch background task for native Windows file picker (`handle_windows_file_dialog`).
     - Click `Upload another resume` link with Playwright `expect_file_chooser`.
     - Set file on file chooser and await native dialog completion.
     - **Active Confirmation Loop:** Poll modal DOM until `isUploading` / progress spinner disappears and uploaded filename is confirmed attached.
  9. **Recruiter Pitch:** Draft personalized greeting (`Hi <RecruiterName>,`) referencing required technical skills and immediate notice.
  10. Human-type pitch into message textarea.
  11. Click `Send` / Submit application.
  12. Record in `JobTracker` and notify via Email.

---

## 📜 4. Global Operating Rules & Constraints

### 4.1 Experience Screening Protocol
* **Target Bracket:** Default 0–2 Years (or candidate-specific range).
* **Strict Exclusion Patterns:**
  ```python
  SENIOR_TITLE_PATTERNS = [
      r"\b(?:senior|sr\.?|lead|principal|staff|architect|manager|director|vp|head\s+of)\b",
      r"\b(?:tech\s*lead|team\s*lead|pod\s*lead|module\s*lead)\b",
      r"\b(?:specialist|engineer|analyst|associate)\s+(?:iii|iv|v|vi|3|4|5|6)\b",
      r"\b(?:[3-9]|\d{2})\s*\+\s*(?:years?|yrs?)\b",
  ]
  ```
* **Exception Rule:** On specialized matching feeds like Cutshort Profile Matcher, process all recommended matching cards directly without client-side title rejection.

### 4.2 ATS Resume Engine Architecture
* **Library:** `reportlab` (Pure Python vector PDF generation).
* **Target Length:** Strictly **1 Single Page** ($< 500$ words).
* **Formatting Rules:**
  - Header: Candidate Name, Phone, Email, LinkedIn, Location.
  - Section 1: Professional Summary (Tailored to role title and domain keywords).
  - Section 2: Technical / Core Domain Competencies (Categorized table).
  - Section 3: Professional Experience & Projects (Action-driven bullets with quantified impact).
  - Section 4: Education & Certifications.
* **Storage Structure:**
  ```
  resumes/
  ├── cutshort/
  ├── hirist/
  ├── linkedin/
  ├── indeed/
  ├── ycombinator/
  └── aggregator/
  ```

### 4.3 Database State & Deduplication Protocol
* Every scanned, evaluated, dry-run, and applied job is persisted in SQLite / PostgreSQL via `JobTracker`:
  ```python
  JobTracker.record_job(
      portal="cutshort",
      company="Tracxn",
      title="Software Engineer",
      job_url="https://...",
      status="APPLIED" # APPLIED | DRY_RUN | SKIPPED_EXP | DUPLICATE
  )
  ```
* Prevents duplicate applications across sessions or between API and Browser agents.

---

## 📝 5. Universal Prompt for AI to Clone this System for Any Domain

```markdown
You are an expert Autonomous Agent Architect. Build a complete, production-grade 3-Phase Autonomous Job Agent for the following candidate profile:

Candidate Profile:
- Name: [Candidate Name]
- Email / Phone: [Email / Phone]
- Target Domain: [e.g. Finance / Tech / Marketing / Data Science]
- Target Roles: [List of 5-8 Target Roles, e.g. Financial Analyst, Investment Banking Analyst, Corporate FP&A, Risk Analyst]
- Experience Level: [e.g. 0-2 Years Entry/Associate]
- Location: [e.g. India / US / Remote]
- Notice Period: [e.g. Immediate / 0 Days]

System Architecture Requirements:
1. Phase 1 (ATS & Job Boards Aggregator):
   - Ingest from job APIs (RemoteOK, Greenhouse, Lever, Ashby, Himalayas).
   - Evaluate match with Gemini (>= 65%).
   - Generate tailored 1-page ATS PDF resumes using ReportLab in resumes/aggregator/.
   - Send Email & WhatsApp notifications + Excel summary report.

2. Phase 2 (LinkedIn Recruiter Feed Outreach):
   - Scan recruiter posts in LinkedIn feed.
   - Extract verified recruiter emails.
   - Send cold outreach emails with tailored ATS resume attached.

3. Phase 3 (Sequential Multi-Board Browser Auto-Apply):
   - Single Chrome Window via CDP port 9222 (no isolated sandboxes).
   - Sequentially execute: LinkedIn -> Indeed -> Y Combinator -> Hirist -> Cutshort.
   - Target at least 20 applications per portal.
   - If 0 jobs found or feed exhausted after 3 empty scrolls, automatically progress to next portal.
   - Handle form filling with Gemini AI reasoning.
   - Handle native Windows file upload dialogs and Playwright file choosers.
   - Save resumes into dedicated subfolders (resumes/linkedin/, resumes/indeed/, resumes/cutshort/, etc.).
   - Use clean ATS PDF naming without multiple dots to satisfy S3 signedUrl validators.

Build the entire codebase following clean Python async architecture with FastAPI, SQLAlchemy, APScheduler, Playwright, ReportLab, and Google Gemini SDK.
```
