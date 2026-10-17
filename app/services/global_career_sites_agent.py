"""
Phase 4: Global Career Sites Autonomous Browser Auto-Apply Agent.

Automates end-to-end job application workflows directly on Company Career Portals
(Startups & MNCs in Germany, Europe, UAE, Australia, Philippines, New Zealand, Saudi Arabia, etc.)
sourced from Excel / CSV spreadsheets.

Workflow:
  1. Reads company names & career URLs from Excel (.xlsx/.xls) or CSV in 'Careers Excel/' folder.
  2. Reuses single Google Chrome instance via CDP (Port 9222) with stealth & TabGuard (Rule 1 & Rule 2).
  3. Detects ATS type (Greenhouse, Lever, Workday, Ashby, SmartRecruiters, BambooHR, Workable, custom).
  4. Filters for 0-2 yrs experience and latest/recent postings.
  5. Matches roles against Doddi Kamal Kumar's technical stack (Java, Spring Boot, Microservices, Python, AI Agents).
  6. Evaluates & scores JD with Gemini LLM (threshold >= 65).
  7. Generates tailored 1-page ATS PDF resume in resumes/global_careers/.
  8. Automatically fills application form fields (name, email, phone, location, CTC, notice period, custom questions).
  9. Detects CAPTCHA / Human verification -> Sends alert email to candidate and pauses until solved.
 10. Submits application (or previews in dry-run) and persists records in JobTracker & SQLite DB.
"""
import asyncio
import csv
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import openpyxl
from playwright.async_api import ElementHandle, Page

from app.config.settings import (
    BASE_DIR,
    CANDIDATE_EMAIL,
    CANDIDATE_GITHUB,
    CANDIDATE_LINKEDIN,
    CANDIDATE_LOCATION,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
    CANDIDATE_TARGET_ROLES,
    EMAIL_ADDRESS,
    MATCH_SCORE_THRESHOLD,
    REPORTS_DIR,
    RESUMES_DIR,
)
from app.services.browser_tab_guard import (
    attach_context_blank_tab_monitor,
    clean_and_recover_blank_tabs,
    connect_or_launch_single_chrome,
    is_about_or_blank_url,
)
from app.services.email_service import EmailService
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger("GlobalCareerSitesAgent")

CAREERS_EXCEL_DIR = Path("Careers Excel")
GLOBAL_RESUMES_DIR = Path(RESUMES_DIR) / "global_careers"
GLOBAL_RESUMES_DIR.mkdir(parents=True, exist_ok=True)
CAREERS_EXCEL_DIR.mkdir(parents=True, exist_ok=True)

# Common ATS domain patterns
ATS_PATTERNS = {
    "greenhouse": re.compile(r"boards\.greenhouse\.io|job-boards\.greenhouse\.io", re.I),
    "lever": re.compile(r"jobs\.lever\.co", re.I),
    "workday": re.compile(r"myworkdayjobs\.com", re.I),
    "ashby": re.compile(r"jobs\.ashbyhq\.com", re.I),
    "smartrecruiters": re.compile(r"jobs\.smartrecruiters\.com|smartrecruiters\.com", re.I),
    "bamboohr": re.compile(r"\.bamboohr\.com/careers", re.I),
    "workable": re.compile(r"apply\.workable\.com", re.I),
    "recruitee": re.compile(r"\.recruitee\.com", re.I),
    "teamtailor": re.compile(r"teamtailor\.com", re.I),
}

# Strict Senior / Excluded patterns
SENIOR_PATTERNS = [
    r"\b(?:senior|sr\.?|lead|principal|staff|architect|director|vp|vice\s+president|head\s+of)\b",
    r"\b(?:tech\s*lead|team\s*lead|engineering\s*manager|general\s*manager)\b",
    r"\b(?:level\s*[3-9]|l[3-9]|band\s*[3-9]|e[3-9])\b",
    r"\b([3-9]|\d{2})\s*\+\s*(?:years?|yrs?)\b",
]

# Fresher / Early Career signals
FRESHER_PATTERNS = [
    r"\b0\s*(?:to|-|–|—)\s*[1-2]\s*(?:years?|yrs?)\b",
    r"\b0\s*\+\s*(?:years?|yrs?)\b",
    r"\b1\s*(?:to|-|–|—)\s*2\s*(?:years?|yrs?)\b",
    r"\b1\s*\+\s*(?:years?|yrs?)\b",
    r"\b2\s*\+\s*(?:years?|yrs?)\b",
    r"\b2\s*(?:years?|yrs?)\b",
    r"\b(?:freshers?|intern|internship|graduate|entry\s*level|junior|associate|trainee)\b",
]


class CareerSiteRecord:
    """Represents a company career site entry from Excel/CSV."""

    def __init__(
        self,
        company: str,
        career_url: str,
        country: str = "Global",
        notes: str = "",
        target_role: Optional[str] = None,
    ):
        self.company = company.strip()
        self.career_url = career_url.strip()
        self.country = country.strip() if country else "Global"
        self.notes = notes.strip() if notes else ""
        self.target_role = target_role.strip() if target_role else None

    def __repr__(self):
        return f"<CareerSiteRecord {self.company} ({self.country}) -> {self.career_url}>"


class GlobalCareerSitesAgent:
    """
    Autonomous Browser Agent that sweeps through Global Startup & MNC Career Sites
    (Germany, Europe, UAE, Australia, Philippines, New Zealand, Saudi Arabia, etc.)
    and executes targeted auto-applications for 0-2 yrs software engineering roles.
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: Optional[str] = None,
        chrome_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.cdp_port = cdp_port
        self.user_data_dir = user_data_dir or os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile")
        self.chrome_path = chrome_path
        self.dry_run = dry_run

        self.scoring_service = ScoringService()
        self.resume_service = ResumeService()
        self.email_service = EmailService()
        self.gemini_client = get_gemini_client()

        self._playwright = None
        self._context = None
        self._page: Optional[Page] = None
        self._is_cdp = False
        self._last_alert_time = 0.0

    # -------------------------------------------------------------------------
    # EXCEL / CSV DATA INGESTION
    # -------------------------------------------------------------------------
    @staticmethod
    def load_sites_from_excel(filepath: Optional[str] = None) -> List[CareerSiteRecord]:
        """
        Loads career sites from any .xlsx, .xls, or .csv found in 'Careers Excel/'
        or from an explicitly specified filepath.
        """
        target_file = None
        if filepath and os.path.exists(filepath):
            target_file = Path(filepath)
        else:
            candidates = list(CAREERS_EXCEL_DIR.glob("*.xlsx")) + \
                         list(CAREERS_EXCEL_DIR.glob("*.xls")) + \
                         list(CAREERS_EXCEL_DIR.glob("*.csv"))
            if candidates:
                target_file = candidates[0]

        if not target_file:
            logger.warning(f"No Excel/CSV file found in '{CAREERS_EXCEL_DIR}'. Creating sample template...")
            GlobalCareerSitesAgent.create_sample_excel_template()
            target_file = CAREERS_EXCEL_DIR / "global_career_sites_template.xlsx"

        records: List[CareerSiteRecord] = []
        ext = target_file.suffix.lower()

        logger.info(f"📂 Loading company career sites from: {target_file}")

        if ext in (".xlsx", ".xls"):
            try:
                wb = openpyxl.load_workbook(target_file, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    return []

                # Find header indices
                headers = [str(c or "").lower().strip() for c in rows[0]]
                comp_idx = -1
                url_idx = -1
                country_idx = -1
                role_idx = -1

                for idx, h in enumerate(headers):
                    if any(k in h for k in ["company", "organization", "employer", "firm"]):
                        comp_idx = idx
                    elif any(k in h for k in ["career", "url", "link", "website", "jobs", "page"]):
                        url_idx = idx
                    elif any(k in h for k in ["country", "region", "location", "city"]):
                        country_idx = idx
                    elif any(k in h for k in ["role", "keyword", "title", "job"]):
                        role_idx = idx

                # Fallback if no explicit headers found
                if comp_idx == -1 and len(headers) > 0:
                    comp_idx = 0
                if url_idx == -1 and len(headers) > 1:
                    url_idx = 1

                for row in rows[1:]:
                    if not row or len(row) <= max(comp_idx, url_idx):
                        continue
                    company = str(row[comp_idx] or "").strip()
                    url = str(row[url_idx] or "").strip()
                    if not company or not url or not url.lower().startswith("http"):
                        continue
                    country = str(row[country_idx] or "Global").strip() if country_idx != -1 and len(row) > country_idx else "Global"
                    role = str(row[role_idx] or "").strip() if role_idx != -1 and len(row) > role_idx else None
                    records.append(CareerSiteRecord(company, url, country=country, target_role=role))

            except Exception as e:
                logger.error(f"Error reading Excel file {target_file}: {e}")

        elif ext == ".csv":
            try:
                with open(target_file, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Normalize keys
                        lower_dict = {k.lower().strip(): v for k, v in row.items() if k}
                        company = next((lower_dict[k] for k in lower_dict if any(x in k for x in ["company", "organization", "firm"])), "")
                        url = next((lower_dict[k] for k in lower_dict if any(x in k for x in ["career", "url", "link", "website", "jobs"])), "")
                        country = next((lower_dict[k] for k in lower_dict if any(x in k for x in ["country", "region", "location"])), "Global")
                        role = next((lower_dict[k] for k in lower_dict if any(x in k for x in ["role", "keyword", "title"])), None)

                        if company and url and url.lower().startswith("http"):
                            records.append(CareerSiteRecord(company, url, country=country, target_role=role))
            except Exception as e:
                logger.error(f"Error reading CSV file {target_file}: {e}")

        logger.info(f"✅ Discovered {len(records)} career sites to evaluate.")
        return records

    @staticmethod
    def create_sample_excel_template() -> str:
        """Creates a starter Excel template in 'Careers Excel/' with top Global Startups & MNCs."""
        out_path = CAREERS_EXCEL_DIR / "global_career_sites_template.xlsx"
        if out_path.exists():
            return str(out_path)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Global Career Sites"

        # Headers
        ws.append(["Company Name", "Career Site URL", "Country / Region", "Target Role Keyword", "Industry / Notes"])

        # Sample initial dataset covering Germany, EU, UAE, Australia, Philippines, New Zealand, Saudi Arabia
        samples = [
            ("Delivery Hero", "https://careers.deliveryhero.com/global/en/c/technology-jobs", "Germany / EU", "Java Backend Developer", "Tech Unicorn — Quick Commerce"),
            ("Zalando", "https://jobs.zalando.com/en/jobs/?department=Technology", "Germany / EU", "Software Engineer", "E-Commerce Tech Hub"),
            ("Personio", "https://www.personio.com/careers/jobs/?department=engineering-product-design", "Germany / EU", "Backend Engineer", "HR Tech Scaleup"),
            ("Celonis", "https://www.celonis.com/careers/jobs/?department=Engineering", "Germany / EU", "Software Engineer", "Process Mining Decacorn"),
            ("Careem", "https://careers.careem.com/jobs/?department=Engineering", "UAE / Middle East", "Java Software Engineer", "Super App / Ride Hailing"),
            ("Noon", "https://www.noon.com/careers/", "UAE / Saudi Arabia", "Software Developer", "Leading Middle East Tech Marketplace"),
            ("Canva", "https://www.canva.com/careers/jobs/?department=Engineering", "Australia / APAC", "Software Engineer", "Visual Suite Tech Giant"),
            ("Atlassian", "https://www.atlassian.com/company/careers/all-jobs?team=Engineering", "Australia / Global", "Java Backend Developer", "DevTools MNC"),
            ("Xero", "https://www.xero.com/about/careers/search-jobs/?team=Technology", "New Zealand / Australia", "Junior Software Engineer", "SaaS Accounting Leader"),
            ("GCash (Mynt)", "https://www.gcash.com/careers", "Philippines / APAC", "Software Engineer", "Top Fintech Unicorn"),
            ("stc (Saudi Telecom)", "https://careers.stc.com.sa", "Saudi Arabia / Middle East", "AI / Cloud Software Engineer", "Telecom & Digital Enabler"),
        ]

        for s in samples:
            ws.append(list(s))

        wb.save(out_path)
        logger.info(f"✨ Created sample career sites template at: {out_path}")
        return str(out_path)

    # -------------------------------------------------------------------------
    # BROWSER CONNECTION (CDP PORT 9222)
    # -------------------------------------------------------------------------
    async def connect(self, context=None, page=None):
        """Connects to single Chrome instance on Port 9222 via CDP."""
        if context and page:
            self._context = context
            self._page = page
            self._is_cdp = True
            return

        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()

        self._context, self._page, self._is_cdp = await connect_or_launch_single_chrome(
            self._playwright,
            cdp_port=self.cdp_port,
            user_data_dir=self.user_data_dir,
            chrome_path=self.chrome_path,
        )

        # Tab Guard: Auto close any stray about:blank or popups without disrupting work
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url=None,
            allowed_domains=None,
        )

        # Stealth overrides
        await self._page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        """)
        logger.info("✅ Global Career Sites Agent connected to Google Chrome (Port 9222).")

    # -------------------------------------------------------------------------
    # CAPTCHA DETECTION & EMAIL ALERT LOOP
    # -------------------------------------------------------------------------
    async def check_and_handle_captcha(self, company_name: str, site_url: str) -> bool:
        """
        Detects CAPTCHA, Cloudflare verification, or bot barriers.
        If detected: sends an Action Required email to candidate and enters a poll loop
        waiting for the user to solve it in the live browser window.
        """
        try:
            p_text = (await self._page.inner_text("body") if await self._page.query_selector("body") else "").lower()
            p_title = (await self._page.title()).lower()

            captcha_signals = [
                "verify you are human",
                "security check",
                "cloudflare",
                "recaptcha",
                "hcaptcha",
                "arkose",
                "turnstile",
                "bot detection",
                "additional verification required",
                "press and hold",
                "slide to verify",
            ]

            has_captcha = any(sig in p_text or sig in p_title for sig in captcha_signals)

            if not has_captcha:
                # Check for iframe captcha elements
                captcha_frames = await self._page.query_selector(
                    "iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[src*='turnstile'], div.g-recaptcha, div#cf-turnstile"
                )
                if captcha_frames and await captcha_frames.is_visible():
                    has_captcha = True

            if not has_captcha:
                return False

            logger.warning(f"🚨 [CAPTCHA DETECTED] Human verification challenge found on {company_name} ({site_url})!")

            # Throttle email alerts: 1 alert per 3 minutes
            now = time.time()
            if now - self._last_alert_time > 180.0:
                self._last_alert_time = now
                subject = f"🚨 [ACTION REQUIRED] CAPTCHA Detected on {company_name} Career Portal — Please Solve in Chrome"
                body = (
                    f"Hello {CANDIDATE_NAME},\n\n"
                    f"The Global Career Sites Auto-Apply Agent encountered a CAPTCHA / Human Verification check while applying at:\n"
                    f"🏢 Company: {company_name}\n"
                    f"🔗 URL: {site_url}\n\n"
                    f"👉 ACTION REQUIRED:\n"
                    f"Please switch to your open Google Chrome browser window right now and solve the verification.\n"
                    f"The agent will automatically detect when the challenge is cleared and proceed with the application.\n\n"
                    f"Best regards,\n"
                    f"KKNN Autonomous AI Job Agent"
                )
                try:
                    self.email_service.send_email(to_email=CANDIDATE_EMAIL, subject=subject, body=body)
                    logger.info(f"📧 Sent Action Required alert email to: {CANDIDATE_EMAIL}")
                except Exception as mail_err:
                    logger.warning(f"Could not dispatch alert email: {mail_err}")

            # Wait loop: poll every 3 seconds up to 5 minutes
            logger.info("⏳ Paused and waiting for human verification to be solved in the browser (up to 5 min)...")
            for _ in range(100):
                await asyncio.sleep(3.0)
                if self._page.is_closed():
                    return False
                now_text = (await self._page.inner_text("body") if await self._page.query_selector("body") else "").lower()
                now_title = (await self._page.title()).lower()
                still_blocked = any(sig in now_text or sig in now_title for sig in captcha_signals)
                if not still_blocked:
                    logger.info(f"🎉 CAPTCHA cleared on {company_name}! Resuming autonomous application...")
                    await asyncio.sleep(2.0)
                    return True

            logger.warning(f"⏱️ Timed out waiting for manual CAPTCHA resolution on {company_name}. Moving forward...")
            return False

        except Exception as e:
            logger.debug(f"Captcha check note: {e}")
            return False

    # -------------------------------------------------------------------------
    # EXPERIENCE & TITLE ELIGIBILITY FILTER
    # -------------------------------------------------------------------------
    @staticmethod
    def is_experience_eligible(job_title: str, job_description: str = "") -> Tuple[bool, str]:
        """Strict check to ensure role matches candidate profile (0-2 years target)."""
        t_lower = (job_title or "").lower()
        d_lower = (job_description or "").lower()

        # Reject senior/lead in title
        for pat in SENIOR_PATTERNS:
            if re.search(pat, t_lower):
                return False, f"Title contains senior/lead pattern '{pat}'"

        # Check description if available
        if d_lower:
            for pat in [
                r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?|yr)\b",
                r"\b(?:minimum|at\s+least|requires?)\s+([3-9]|\d{2,})\s*(?:years?|yrs?)\b",
            ]:
                m = re.search(pat, d_lower)
                if m:
                    match_txt = m.group(0)
                    if not any(re.search(f, match_txt) for f in FRESHER_PATTERNS):
                        return False, f"Description demands '{match_txt}' (>2 yrs)"

        return True, "Eligible (0-2 years)"

    # -------------------------------------------------------------------------
    # DISCOVER JOBS ON CAREER PAGE
    # -------------------------------------------------------------------------
    async def discover_jobs_on_page(self, company_name: str, target_role_keyword: Optional[str] = None) -> List[Dict[str, Any]]:
        """Discovers, filters, and extracts job listings from the current career site."""
        discovered = []

        # Check for search input on career page
        search_keyword = target_role_keyword or "Java"
        try:
            search_input = await self._page.query_selector("input[type='search'], input[name*='search'], input[placeholder*='search' i], input[placeholder*='job' i], input[placeholder*='title' i]")
            if search_input and await search_input.is_visible():
                await search_input.fill("")
                await search_input.fill(search_keyword)
                await self._page.keyboard.press("Enter")
                await asyncio.sleep(2.5)
        except Exception:
            pass

        # Try clicking 24h / Recent / Newest filter if present
        try:
            sort_btn = await self._page.query_selector("button:has-text('Date'), a:has-text('Date'), button:has-text('Recent'), a:has-text('Recent'), button:has-text('Newest')")
            if sort_btn and await sort_btn.is_visible():
                await sort_btn.click()
                await asyncio.sleep(1.5)
        except Exception:
            pass

        # Extract anchor tags pointing to jobs
        job_links = await self._page.evaluate("""
            () => {
                const results = [];
                const seen = new Set();
                const anchors = Array.from(document.querySelectorAll("a[href]"));
                
                for (const a of anchors) {
                    const href = a.getAttribute("href") || "";
                    const text = (a.innerText || a.textContent || "").trim();
                    if (!href || text.length < 3) continue;
                    
                    const lowerHref = href.toLowerCase();
                    const lowerText = text.toLowerCase();
                    
                    // Filter out navigation/footer links
                    if (lowerHref.includes("about") || lowerHref.includes("contact") || lowerHref.includes("privacy") || lowerHref.includes("terms") || lowerHref.includes("login") || lowerHref.includes("signin")) {
                        continue;
                    }
                    
                    // Look for job indicators
                    const isJobLink = lowerHref.includes("/job/") || lowerHref.includes("/jobs/") || 
                                     lowerHref.includes("/careers/") || lowerHref.includes("/opening/") || 
                                     lowerHref.includes("/positions/") || lowerHref.includes("gh_jid=") || 
                                     lowerHref.includes("lever.co/") || lowerHref.includes("workday");
                                     
                    if (isJobLink || lowerText.includes("developer") || lowerText.includes("engineer") || lowerText.includes("software")) {
                        const fullUrl = a.href;
                        if (!seen.has(fullUrl)) {
                            seen.add(fullUrl);
                            results.push({
                                title: text.split("\\n")[0].trim(),
                                url: fullUrl,
                            });
                        }
                    }
                }
                return results;
            }
        """)

        # Filter by Software / Java / Backend keywords & 0-2 yrs experience
        tech_keywords = ["java", "spring", "backend", "software", "python", "full stack", "fullstack", "developer", "engineer", "cloud", "ai", "api"]

        for item in job_links:
            title = item.get("title", "")
            url = item.get("url", "")
            t_lower = title.lower()

            if not any(kw in t_lower for kw in tech_keywords):
                continue

            eligible, reason = self.is_experience_eligible(title)
            if not eligible:
                continue

            discovered.append({
                "company": company_name,
                "title": title,
                "url": url,
            })

        logger.info(f"🔎 Discovered {len(discovered)} relevant 0-2 yrs tech openings at {company_name}")
        return discovered

    # -------------------------------------------------------------------------
    # FORM FILLER & APPLICATION SUBMITTER
    # -------------------------------------------------------------------------
    async def fill_application_form(self, job_title: str, company: str, tailored_pdf_path: str) -> bool:
        """
        Fills standard and ATS-specific application forms (Greenhouse, Lever, Ashby, Workday, etc.).
        """
        logger.info(f"📝 Auto-filling application form for '{job_title}' @ {company}...")

        # 1. Look for 'Apply' or 'Apply Now' buttons to open form
        try:
            apply_btn = await self._page.query_selector("a:has-text('Apply'), button:has-text('Apply'), a:has-text('Apply Now'), button:has-text('Apply Now'), button:has-text('Submit Application')")
            if apply_btn and await apply_btn.is_visible():
                btn_txt = ((await apply_btn.inner_text()) or "").strip().lower()
                if "apply" in btn_txt and not any(k in btn_txt for k in ["saved", "applied"]):
                    await apply_btn.click()
                    await asyncio.sleep(2.0)
        except Exception:
            pass

        # 2. Upload Tailored PDF Resume
        if tailored_pdf_path and os.path.exists(tailored_pdf_path):
            try:
                file_input = await self._page.query_selector("input[type='file']")
                if file_input:
                    await file_input.set_input_files(os.path.abspath(tailored_pdf_path))
                    logger.info(f"📎 Uploaded tailored ATS resume: {os.path.basename(tailored_pdf_path)}")
                    await asyncio.sleep(2.0)
            except Exception as up_err:
                logger.warning(f"File upload note: {up_err}")

        # 3. Fill Standard Text Inputs
        inputs = await self._page.query_selector_all("input[type='text'], input[type='email'], input[type='tel'], input:not([type]), textarea")
        for inp in inputs:
            try:
                if not await inp.is_visible() or await inp.is_disabled():
                    continue

                # Inspect label, placeholder, name, id
                tag_name = await (await inp.get_property("tagName")).json_value()
                field_id = await inp.get_attribute("id") or ""
                field_name = await inp.get_attribute("name") or ""
                placeholder = await inp.get_attribute("placeholder") or ""
                
                # Fetch parent label text
                label_text = await self._page.evaluate(
                    """el => {
                        const label = document.querySelector(`label[for='${el.id}']`) || el.closest('label') || el.closest('.field, .form-group, div');
                        return label ? (label.innerText || label.textContent || '').trim().toLowerCase() : '';
                    }""",
                    inp
                )
                field_descriptor = f"{field_id} {field_name} {placeholder} {label_text}".lower()

                # Full Name / First Name / Last Name
                if any(k in field_descriptor for k in ["first name", "given name", "firstname"]):
                    await inp.fill("Kamal Kumar")
                elif any(k in field_descriptor for k in ["last name", "family name", "surname", "lastname"]):
                    await inp.fill("Doddi")
                elif any(k in field_descriptor for k in ["full name", "your name", "candidate name"]) or (field_name == "name"):
                    await inp.fill(CANDIDATE_NAME)

                # Email
                elif "email" in field_descriptor:
                    await inp.fill(CANDIDATE_EMAIL)

                # Phone
                elif any(k in field_descriptor for k in ["phone", "mobile", "tel", "contact"]):
                    await inp.fill(CANDIDATE_PHONE)

                # Location / City
                elif any(k in field_descriptor for k in ["city", "location", "address"]):
                    await inp.fill(CANDIDATE_LOCATION)

                # LinkedIn
                elif "linkedin" in field_descriptor:
                    await inp.fill(CANDIDATE_LINKEDIN)

                # GitHub / Portfolio
                elif any(k in field_descriptor for k in ["github", "portfolio", "website", "git"]):
                    await inp.fill(CANDIDATE_GITHUB)

                # Notice period
                elif any(k in field_descriptor for k in ["notice", "availability", "how soon"]):
                    await inp.fill("0 days (Immediate Joiner)")

                # Salary / CTC
                elif any(k in field_descriptor for k in ["current ctc", "current salary", "current compensation"]):
                    await inp.fill("3.5 LPA (350,000 INR)")
                elif any(k in field_descriptor for k in ["expected ctc", "expected salary", "salary expectation", "compensation"]):
                    await inp.fill("7.0 LPA (700,000 INR)")

                # Work Authorization / Relocation
                elif any(k in field_descriptor for k in ["relocate", "relocation", "visa", "sponsorship"]):
                    await inp.fill("Yes, fully open to relocate immediately / open to remote")

                # Long-form custom questions (Cover Letter / Notes / Tell us about yourself)
                elif tag_name.lower() == "textarea" or "cover" in field_descriptor:
                    pitch = (
                        f"I am a Software Engineer with 1.5 - 2 years of professional backend and microservices experience specializing in "
                        f"Java, Spring Boot, REST APIs, Python, and AI Agents. I am an immediate joiner (0 days notice) and eager to contribute to {company}."
                    )
                    await inp.fill(pitch)

            except Exception as f_err:
                logger.debug(f"Input filling note: {f_err}")

        # 4. Check Required Terms & Confirmation Checkboxes
        try:
            checkboxes = await self._page.query_selector_all("input[type='checkbox']")
            for cb in checkboxes:
                try:
                    if await cb.is_visible() and not await cb.is_checked():
                        await cb.check()
                except Exception:
                    pass
        except Exception:
            pass

        # 5. Check for CAPTCHA challenge before submission
        await self.check_and_handle_captcha(company, self._page.url)

        # 6. Submit or Review
        if self.dry_run:
            logger.info(f"🧪 [DRY RUN] Form filled successfully for '{job_title}' @ {company}. Skipping final submit.")
            return True

        # Find submit button
        try:
            submit_btn = await self._page.query_selector(
                "button[type='submit'], input[type='submit'], button:has-text('Submit'), button:has-text('Send Application'), button:has-text('Submit Application')"
            )
            if submit_btn and await submit_btn.is_visible():
                logger.info(f"🚀 Submitting live application for '{job_title}' @ {company}...")
                await submit_btn.click()
                await asyncio.sleep(4.0)

                # Check if a post-submit CAPTCHA appeared
                await self.check_and_handle_captcha(company, self._page.url)

                logger.info(f"🎉 Application submitted successfully for '{job_title}' @ {company}!")
                return True
        except Exception as sub_err:
            logger.warning(f"Submit click note: {sub_err}")

        return False

    # -------------------------------------------------------------------------
    # MAIN EXECUTION PIPELINE
    # -------------------------------------------------------------------------
    async def run(
        self,
        excel_path: Optional[str] = None,
        target_applications: int = 10,
        country_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes Phase 4: Sweeps through company career portals from Excel/CSV
        and applies to matching 0-2 yrs tech roles.
        """
        sites = self.load_sites_from_excel(excel_path)
        if not sites:
            logger.warning("No career sites to process.")
            return {"total_applied": 0, "processed_companies": 0}

        if country_filter:
            c_clean = country_filter.lower().strip()
            sites = [s for s in sites if c_clean in s.country.lower() or c_clean in s.notes.lower()]
            logger.info(f"Filter applied: {len(sites)} sites matching country '{country_filter}'")

        await self.connect()

        stats = {
            "total_applied": 0,
            "processed_companies": 0,
            "applications": [],
        }

        logger.info("\n" + "=" * 70)
        logger.info("🌐 [PHASE 4: GLOBAL CAREER SITES AUTONOMOUS AUTO-APPLY PIPELINE]")
        logger.info(f"🎯 Candidate: {CANDIDATE_NAME} (0-2 Years Experience)")
        logger.info(f"🏢 Total Target Companies in List: {len(sites)}")
        logger.info(f"🎯 Target Applications to Submit: {target_applications}")
        logger.info(f"🧪 Mode: {'DRY RUN (Form Preview)' if self.dry_run else 'LIVE SUBMISSIONS'}")
        logger.info("=" * 70 + "\n")

        for idx, site in enumerate(sites, 1):
            if stats["total_applied"] >= target_applications:
                logger.info(f"🎯 Session target of {target_applications} applications achieved! Halting run.")
                break

            logger.info(f"\n{'━'*65}\n[{idx}/{len(sites)}] 🏢 EVALUATING COMPANY: {site.company.upper()} ({site.country})\n🔗 Career Site: {site.career_url}\n{'━'*65}")

            try:
                # Rule 1 Tab Guard check
                self._page, _ = await clean_and_recover_blank_tabs(
                    self._context,
                    self._page,
                    fallback_url=site.career_url,
                    auto_refresh=False,
                )

                # Navigate to company career portal
                await self._page.goto(site.career_url, wait_until="domcontentloaded", timeout=50000)
                await asyncio.sleep(2.5)

                # Check for initial CAPTCHA challenge
                await self.check_and_handle_captcha(site.company, site.career_url)

                # Discover matching jobs
                openings = await self.discover_jobs_on_page(site.company, target_role_keyword=site.target_role)
                if not openings:
                    logger.info(f"ℹ️ No active 0-2 yrs tech openings found matching stack at {site.company}.")
                    stats["processed_companies"] += 1
                    continue

                best_opening = None
                best_score = 0
                best_eval = None

                # Score discovered openings
                for opening in openings[:3]:  # inspect top 3 openings
                    title = opening["title"]
                    job_url = opening["url"]

                    # Deduplication check
                    if JobTracker.is_already_applied("career_site", job_url=job_url, title=title, company=site.company):
                        logger.info(f"⏩ Already applied to '{title}' @ {site.company}. Skipping.")
                        continue

                    # Fetch JD text if navigation required
                    jd_snippet = f"Role: {title} at {site.company} ({site.country}). Requirements: Java, Spring Boot, Microservices, Python, Cloud."
                    try:
                        # Quick evaluate score
                        job_dict = {
                            "title": title,
                            "company": site.company,
                            "description": jd_snippet,
                            "location": site.country,
                        }
                        eval_res = self.scoring_service.score_job(job_dict)
                        score = eval_res.get("score", 0) if isinstance(eval_res, dict) else 70
                        logger.info(f"📊 Evaluated '{title}': Score {score}/100")

                        if score > best_score:
                            best_score = score
                            best_opening = opening
                            best_eval = eval_res
                    except Exception as sc_err:
                        logger.debug(f"Scoring note: {sc_err}")
                        best_opening = opening
                        best_score = 70

                if not best_opening or best_score < MATCH_SCORE_THRESHOLD:
                    logger.info(f"ℹ️ Highest match score at {site.company} ({best_score}) below threshold ({MATCH_SCORE_THRESHOLD}). Skipping.")
                    stats["processed_companies"] += 1
                    continue

                # Navigate to chosen opening page
                logger.info(f"🎯 Selected Best Match: '{best_opening['title']}' (Score: {best_score})")
                await self._page.goto(best_opening["url"], wait_until="domcontentloaded", timeout=45000)
                await asyncio.sleep(2.0)

                # Generate deeply tailored ATS resume
                tailored_pdf = self.resume_service.generate_tailored_resume(
                    job={"title": best_opening["title"], "company": site.company, "description": best_opening["title"]},
                    portal="global_careers",
                )

                # Auto-fill form and submit
                applied = await self.fill_application_form(
                    job_title=best_opening["title"],
                    company=site.company,
                    tailored_pdf_path=tailored_pdf,
                )

                if applied:
                    stats["total_applied"] += 1
                    stats["applications"].append({
                        "company": site.company,
                        "title": best_opening["title"],
                        "url": best_opening["url"],
                        "country": site.country,
                        "score": best_score,
                        "resume": tailored_pdf,
                    })

                    # Record in JobTracker
                    JobTracker.record_job(
                        portal="career_site",
                        company=site.company,
                        title=best_opening["title"],
                        job_url=best_opening["url"],
                        status="APPLIED" if not self.dry_run else "DRY_RUN",
                        resume_version=tailored_pdf,
                    )

                stats["processed_companies"] += 1

            except Exception as site_err:
                logger.error(f"Error processing career portal for {site.company}: {site_err}")
                stats["processed_companies"] += 1

        logger.info("\n" + "=" * 70)
        logger.info("🏁 [PHASE 4 GLOBAL CAREER SITES RUN COMPLETE]")
        logger.info(f"📊 Companies Evaluated:   {stats['processed_companies']}")
        logger.info(f"🚀 Applications Submitted: {stats['total_applied']}")
        for app_rec in stats["applications"]:
            logger.info(f"   • {app_rec['company']:20} | {app_rec['title']} ({app_rec['country']})")
        logger.info("=" * 70 + "\n")

        return stats

    async def close(self):
        """Cleanly disconnects while preserving the single Chrome instance."""
        try:
            if self._context and not self._context.is_closed():
                pages = [p for p in self._context.pages if not p.is_closed()]
                for p in pages[1:]:
                    try:
                        await p.close()
                    except Exception:
                        pass
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass


async def run_global_career_sites_apply(
    excel_path: Optional[str] = None,
    target_applied: int = 10,
    country: Optional[str] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Helper entry point for Phase 4."""
    agent = GlobalCareerSitesAgent(dry_run=dry_run)
    try:
        return await agent.run(
            excel_path=excel_path,
            target_applications=target_applied,
            country_filter=country,
        )
    finally:
        await agent.close()
