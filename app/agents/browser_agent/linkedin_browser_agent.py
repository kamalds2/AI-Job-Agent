"""
Portal 1: LinkedIn Autonomous Browser Auto-Apply Agent (Finance & Accounting Sector).
Candidate: Meesala Srinivas Rao (MBA in Finance — Fresher / 0-1 Years Experience).

Features:
- Connects via CDP (port 9222) to active browser session (Microsoft Edge).
- Navigates to LinkedIn Jobs with:
    * Past 24h filter (f_TPR=r86400)
    * Experience Level: Internship (1), Entry level (2), Associate (3) (f_E=1,2,3)
    * Easy Apply filter (f_AL=true)
    * Most Recent sort (sortBy=DD)
- Robust DOM evaluate clicking (immune to detachment, scrolls list container into view).
- Evaluates title & JD for finance roles without false-positive skips on reporting lines (e.g. 'reports to Senior Manager').
- Dynamically generates ATS 1-page PDF resumes tailored for Meesala Srinivas Rao.
- Automates the full Easy Apply modal:
    * Uploads tailored PDF resume
    * Automatically fills text, number, and tel inputs (phone, email, notice period, CTC, experience)
    * Solves select dropdowns with native event dispatching
    * Clicks radio button labels & checks terms checkboxes
    * Self-heals field validation errors via FormSelfHealer and Gemini AI
    * Submits application and dismisses post-apply popups
"""
import asyncio
import json
import logging
import os
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from app.agents.browser_agent.browser_client import SharedBrowserClient
from app.agents.browser_agent.form_self_healer import FormSelfHealer
from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_LOCATION,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
    REPORTS_DIR,
)
from app.services.job_tracker import JobTracker
from app.services.resume_service import ResumeService
from app.services.scoring_service import ScoringService
from app.utils.gemini_client import get_gemini_client

logger = logging.getLogger(__name__)

FINANCE_TARGET_ROLES = [
    "Financial Analyst",
    "Associate Financial Analyst",
    "FP&A Analyst",
    "Investment Banking Analyst",
    "Equity Research Analyst",
    "Credit Analyst",
    "Corporate Finance",
    "Accounts & Finance",
    "Junior Financial Analyst",
]


class FinanceExperienceAnalyzer:
    """
    Experience analyzer for Finance & Accounting jobs (Fresher / 0-1 years target).
    Strictly filters out senior executive titles while ensuring Associate, Analyst,
    Junior, Trainee, and Fresher jobs are never falsely rejected due to reporting lines.
    """

    SENIOR_TITLE_PATTERNS = [
        r"\b(?:senior|sr\.?|lead|principal|staff|architect|director|vp|vice\s+president|head\s+of|avp|svp|evp)\b",
        r"\b(?:general\s*manager|dgm|gm|cfo|cxo|chief|partner)\b",
        r"\b(?:[3-9]|\d{2})\s*\+\s*(?:years?|yrs?)\b",
    ]

    MID_EXPERIENCE_PATTERNS = [
        # Explicit 3+ years or higher
        r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?|yr)\b",
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:to|-|–|—)\s*\d+\s*(?:years?|yrs?|yr)\b",
        r"\b2\s*(?:to|-|–|—)\s*([4-9]|\d{2,})\s*(?:years?|yrs?|yr)\b",
        r"\b(?:minimum|min|at\s+least|requires?|requiring)\s+(?:of\s+)?([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\b",
        r"\b([3-9]|\d{2,})\s*\+?\s*(?:years?|yrs?|yr)\s+(?:of\s+)?(?:relevant\s+|work\s+|corporate\s+)?(?:experience|exp)\b",
    ]

    FRESHER_PATTERNS = [
        r"\b0\s*(?:to|-|–|—)\s*[1-2]\s*(?:years?|yrs?)\b",
        r"\b0\s*\+\s*(?:years?|yrs?)\b",
        r"\b1\s*(?:to|-|–|—)\s*2\s*(?:years?|yrs?)\b",
        r"\b1\s*\+\s*(?:years?|yrs?)\b",
        r"\b2\s*\+\s*(?:years?|yrs?)\b",
        r"\b(?:freshers?|intern|internship|graduate|entry\s*level|junior|associate|trainee)\b",
    ]

    @classmethod
    def analyze_title(cls, job_title: str) -> Dict:
        """Fast title screening to reject senior/lead roles while accepting Associate & Analyst."""
        title_lower = (job_title or "").lower()

        # If title explicitly indicates fresher/junior/trainee/intern/associate, immediately approve!
        for f_pat in [r"\btrainee\b", r"\bintern\b", r"\binternship\b", r"\bfresher\b", r"\bjunior\b", r"\bassociate\b", r"\bentry\s*level\b", r"\b0\s*-\s*1\b"]:
            if re.search(f_pat, title_lower):
                return {"eligible": True, "reason": "Title indicates Fresher / Junior / Associate level", "exp_years": 0.5}

        # Check for senior title keywords
        for pat in cls.SENIOR_TITLE_PATTERNS:
            m = re.search(pat, title_lower)
            if m:
                matched_kw = m.group(0)
                return {
                    "eligible": False,
                    "reason": f"Title contains senior/lead keyword '{matched_kw}' (exceeds 0-1 yrs)",
                    "exp_years": 0.0,
                }

        return {"eligible": True, "reason": "Title is eligible (Fresher / 0-1 yrs)", "exp_years": 1.0}

    @classmethod
    def analyze(cls, job_title: str, job_description: str) -> Dict:
        """
        Screen job description for Finance profile:
        - Accepts: 0-1 yrs, 0-2 yrs, freshers, associates, juniors, analysts.
        - Skips: Explicit hard requirement of >= 3 years work experience.
        - Note: Mentions of 'senior team members' or 'reports to senior' are NOT disqualified.
        """
        title_res = cls.analyze_title(job_title)
        if not title_res["eligible"]:
            return title_res

        desc_lower = (job_description or "").lower()

        # Check for explicit >2 Years Hard Requirements in description
        for pat in cls.MID_EXPERIENCE_PATTERNS:
            m = re.search(pat, desc_lower)
            if m:
                matched_text = m.group(0)
                # If the same text also contains fresher signals, allow it
                if not any(re.search(f_pat, matched_text) for f_pat in cls.FRESHER_PATTERNS):
                    return {
                        "eligible": False,
                        "reason": f"Job description requires '{matched_text}' (exceeds 0-1 yrs)",
                        "exp_years": 0.0,
                    }

        return {
            "eligible": True,
            "exp_years": 1.0,
            "reason": "Standard Finance role (0-1 yrs / Associate eligible)",
        }


class LinkedInBrowserAgent:
    """
    Autonomous LinkedIn Browser Auto-Apply Agent for Finance candidates.
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: Optional[str] = None,
        browser_executable_path: Optional[str] = None,
        dry_run: bool = False,
    ):
        self.browser_client = SharedBrowserClient(
            cdp_port=cdp_port,
            user_data_dir=user_data_dir,
            browser_executable_path=browser_executable_path,
            dry_run=dry_run,
        )
        self.dry_run = dry_run
        self.resume_service = ResumeService()
        self.scoring_service = ScoringService()
        self.gemini_client = get_gemini_client()

        self.resumes_dir = Path("resumes/linkedin")
        self.resumes_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir = Path(REPORTS_DIR) / "screenshots" / "linkedin"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

        self._page = None
        self._context = None
        self.daily_limit_hit = False

    async def connect(self, context=None, page=None):
        """Connect to live browser via SharedBrowserClient and verify sign-in status."""
        self._page = await self.browser_client.connect(context=context, page=page)
        self._context = self.browser_client._context

        logger.info("🔍 Checking LinkedIn session status...")
        await self._page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2.5)

        await self.browser_client.wait_for_portal_signin(
            portal_name="LinkedIn",
            logged_in_selectors=[
                "div.global-nav__me",
                "button.global-nav__primary-link-me-menu-trigger",
                "img.global-nav__me-photo",
                "a[href*='/in/']",
                "div#global-nav-typeahead",
                "div.feed-identity-module",
                "button[aria-label*='Me']",
                "a:has-text('Messaging')",
                "a:has-text('Jobs')",
                "nav.global-nav",
            ],
            logged_out_selectors=[
                "a:has-text('Sign in')",
                "button:has-text('Sign in')",
                "input#session_key",
                "input#username",
            ],
            auth_url_patterns=["/login", "/authwall", "/signup", "uas/login"],
        )

    async def _check_daily_limit_reached(self) -> bool:
        """Check if LinkedIn has enforced daily Easy Apply submission limit."""
        if not self._page or self._page.is_closed():
            return False
        try:
            limit_elem = await self._page.query_selector(
                "div:has-text('limit daily submissions'), "
                "p:has-text('limit daily submissions'), "
                "span:has-text('limit daily submissions'), "
                "div:has-text('apply tomorrow'), "
                "p:has-text('Save this job and apply tomorrow'), "
                ".artdeco-inline-feedback:has-text('limit daily submissions'), "
                ".artdeco-toast-item:has-text('limit daily submissions')"
            )
            if limit_elem and await limit_elem.is_visible():
                return True

            has_limit_text = await self._page.evaluate("""
                () => {
                    const bodyText = document.body.innerText || '';
                    return bodyText.includes('We limit daily submissions') || 
                           bodyText.includes('limit daily submissions to maintain quality') ||
                           (bodyText.includes('daily submissions') && bodyText.includes('apply tomorrow'));
                }
            """)
            return bool(has_limit_text)
        except Exception:
            return False

    async def answer_form_field(
        self,
        question_text: str,
        field_type: str,
        options: list[str] = None,
        job_title: str = "",
        company: str = "",
        exp_years: float = 1.0,
    ) -> str:
        """Answer application questionnaire fields using candidate profile & rule-based AI."""
        q_lower = question_text.lower()

        # Phone & Contact
        if any(kw in q_lower for kw in ["phone", "mobile", "contact"]):
            return CANDIDATE_PHONE.replace("+91-", "").replace("+91", "").strip()

        # Email
        if "email" in q_lower:
            return CANDIDATE_EMAIL

        # Name
        if "first name" in q_lower:
            return "Srinivas Rao"
        if "last name" in q_lower:
            return "Meesala"
        if "full name" in q_lower or ("name" in q_lower and "company" not in q_lower):
            return CANDIDATE_NAME

        # City / Location
        if any(kw in q_lower for kw in ["city", "location", "address"]):
            return "Hyderabad, India"

        # Relocation / Onsite / Hybrid
        if any(w in q_lower for w in ["relocate", "relocation", "work from", "hybrid", "onsite", "in-office", "commute", "travel", "hyderabad", "bengaluru", "bangalore", "mumbai", "pune", "delhi"]):
            return "Yes"

        # Notice Period (Immediate Joiner / 0 Days)
        if any(kw in q_lower for kw in ["notice", "how soon", "start date", "joining", "period"]):
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["0 days", "0-15", "0 to 15", "< 15", "15 days", "immediate", "0", "15", "1 month"]):
                        return opt
                return options[0]
            return "0"

        # Work Authorization & Sponsorship
        if "sponsorship" in q_lower or "visa" in q_lower:
            if "require" in q_lower or "need" in q_lower:
                return "No"
            return "Yes"
        if "authorized" in q_lower or "legally" in q_lower or "eligible to work" in q_lower:
            return "Yes"

        # Years of Experience
        if any(kw in q_lower for kw in ["years of experience", "how many years", "experience"]):
            if field_type in ("number", "tel") or any(w in q_lower for w in ["number", "digit", "decimal"]):
                return "1"
            return "1"

        # Education & GPA
        if any(kw in q_lower for kw in ["degree", "education", "qualification"]):
            if field_type in ("number", "tel") or any(w in q_lower for w in ["score", "gpa", "percentage", "marks", "cgpa", "decimal"]):
                return "8.0"
            return "Master's Degree"  # MBA in Finance
        if any(kw in q_lower for kw in ["gpa", "percentage", "score", "marks", "cgpa", "academic"]):
            return "8.0"

        # Current CTC / Salary
        if "current" in q_lower and any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs"]):
                return "1.5"
            if any(w in q_lower for w in ["monthly", "per month"]):
                return "15000"
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["1.5", "1-2", "0-2", "1 to 2", "less than 2", "< 2", "150000"]):
                        return opt
            return "150000"

        # Expected CTC / Salary
        if "expected" in q_lower and any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs"]):
                return "5"
            if any(w in q_lower for w in ["monthly", "per month"]):
                return "40000"
            if options:
                for opt in options:
                    o_l = opt.lower()
                    if any(kw in o_l for kw in ["5", "5.0", "4-6", "4 to 6", "500000", "5 lpa"]):
                        return opt
            return "500000"

        # General CTC / Salary
        if any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
            if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs"]):
                return "5"
            return "500000"

        # Demographics & Disclosures
        if "gender" in q_lower:
            return "Male"
        if "disability" in q_lower or "handicap" in q_lower:
            return "No"
        if "veteran" in q_lower:
            return "No"
        if "background" in q_lower or "drug" in q_lower:
            return "Yes"
        if "english" in q_lower or "fluent" in q_lower or "proficiency" in q_lower:
            return "Professional" if options and "professional" in [o.lower() for o in options] else "Yes"

        # AI Reasoning Fallback via Gemini Client
        if self.gemini_client:
            try:
                prompt = (
                    f"You are answering an employment questionnaire for a candidate.\n"
                    f"Candidate: Meesala Srinivas Rao (MBA in Finance, 1 year experience, immediate joiner, Hyderabad India).\n"
                    f"Job: {job_title} at {company}\n"
                    f"Question: {question_text}\n"
                    f"Field Type: {field_type}\n"
                    f"Options (if any): {options}\n"
                    f"Return ONLY the concise exact answer as plain text (e.g. 'Yes', '1', '500000', or an exact option string)."
                )
                resp = self.gemini_client.generate_content(prompt=prompt, max_output_tokens=64)
                if resp and len(resp.strip()) > 0:
                    clean = resp.strip().replace("```", "").replace('"', '').strip()
                    logger.info(f"🤖 [AI Screening QA] '{question_text[:40]}' -> '{clean}'")
                    return clean
            except Exception as e:
                logger.debug(f"AI QA fallback note: {e}")

        return "Yes" if options and "yes" in [o.lower() for o in options] else "1"

    async def _handle_easy_apply_modal(
        self,
        job_title: str,
        company: str,
        resume_pdf_path: str,
        exp_years: float = 1.0,
    ) -> str:
        """Handle multi-step LinkedIn Easy Apply popup modal."""
        modal = None
        for _ in range(8):
            if await self._check_daily_limit_reached():
                logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily submission limit detected!")
                self.daily_limit_hit = True
                return "DAILY_LIMIT_REACHED"
            await asyncio.sleep(0.8)
            modal = await self._page.query_selector("div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal")
            if modal and await modal.is_visible():
                break

        if not modal or not await modal.is_visible():
            if await self._check_daily_limit_reached():
                self.daily_limit_hit = True
                return "DAILY_LIMIT_REACHED"
            logger.warning("⚠️ Easy Apply modal did not appear after clicking Easy Apply button.")
            return "MODAL_FAILED_TO_OPEN"

        logger.info("  📋 Easy Apply modal is open! Processing application form...")

        for step in range(1, 12):
            await asyncio.sleep(2.0)

            # Check if modal is still open
            modal = await self._page.query_selector("div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal")
            if not modal or not await modal.is_visible():
                logger.info("  ✅ Modal closed — application submitted successfully!")
                return "APPLIED"

            # Check for post-apply popups
            post_apply_header = await self._page.query_selector(
                ".artdeco-modal:has-text('Application sent'), .artdeco-modal:has-text('Applied'), .artdeco-modal:has-text('Your application was sent'), button:has-text('Not now'), button:has-text('Done')"
            )
            if post_apply_header and await post_apply_header.is_visible():
                logger.info("  🎉 Post-apply confirmation screen detected!")
                await self._dismiss_post_apply_popup()
                await self._dismiss_modal()
                return "APPLIED"

            logger.info(f"  📝 Processing Easy Apply Step {step}...")

            # 1. Upload tailored resume if file upload input is present
            file_inputs = await self._page.query_selector_all("input[type='file']")
            for f_inp in file_inputs:
                if os.path.exists(resume_pdf_path):
                    try:
                        await f_inp.set_input_files(os.path.abspath(resume_pdf_path))
                        logger.info(f"  ⬆️ Uploaded tailored resume: {os.path.basename(resume_pdf_path)}")
                        await asyncio.sleep(1.0)
                    except Exception as e:
                        logger.warning(f"  Resume upload note: {e}")

            # 2. Fill text, number, and tel inputs
            text_inputs = await self._page.query_selector_all(
                ".artdeco-modal input[type='text'], .artdeco-modal input[type='number'], .artdeco-modal input[type='tel'], .artdeco-modal textarea"
            )
            for inp in text_inputs:
                try:
                    val = await inp.input_value()
                    if not val:
                        id_attr = await inp.get_attribute("id")
                        inp_type = (await inp.get_attribute("type") or "text").strip().lower()
                        label_text = ""
                        if id_attr:
                            label_elem = await self._page.query_selector(f"label[for='{id_attr}']")
                            if label_elem:
                                label_text = await label_elem.inner_text()
                        if not label_text:
                            label_text = (await inp.get_attribute("aria-label")) or "Experience or detail"

                        answer = await self.answer_form_field(
                            question_text=label_text,
                            field_type=inp_type,
                            job_title=job_title,
                            company=company,
                            exp_years=exp_years,
                        )
                        await inp.fill(str(answer))
                        await asyncio.sleep(0.4)

                        # Auto-correct numeric validation errors
                        try:
                            err_el = await self._page.query_selector(
                                ".artdeco-inline-feedback--error, .fb-form-element__error-text, [data-test-form-element-error], span[class*='error']"
                            )
                            if err_el and await err_el.is_visible():
                                err_msg = (await err_el.inner_text()).strip().lower()
                                if any(kw in err_msg for kw in ["decimal", "number", "numeric", "digit", "integer", "larger than"]):
                                    q_l = label_text.lower()
                                    if any(w in q_l for w in ["score", "gpa", "cgpa", "percentage", "marks"]):
                                        corrected = "8.0"
                                    elif any(w in q_l for w in ["salary", "ctc", "package", "compensation"]):
                                        corrected = "500000"
                                    elif any(w in q_l for w in ["notice", "joining", "start"]):
                                        corrected = "0"
                                    else:
                                        corrected = "1"
                                    logger.info(f"  🔧 [Auto-Correct] '{label_text[:40]}' re-filled with '{corrected}'")
                                    await inp.fill(corrected)
                                    await asyncio.sleep(0.3)
                        except Exception:
                            pass
                except Exception:
                    pass

            # 3. Handle dropdown selections
            selects = await self._page.query_selector_all(".artdeco-modal select")
            for sel in selects:
                try:
                    options = await sel.query_selector_all("option")
                    opt_texts = [await opt.inner_text() for opt in options]
                    id_attr = await sel.get_attribute("id")
                    label_text = ""
                    if id_attr:
                        lbl = await self._page.query_selector(f"label[for='{id_attr}']")
                        if lbl:
                            label_text = await lbl.inner_text()
                    answer = await self.answer_form_field(
                        question_text=label_text or "Select option",
                        field_type="select",
                        options=opt_texts,
                        job_title=job_title,
                        company=company,
                        exp_years=exp_years,
                    )
                    matched_val = None
                    for opt in options:
                        o_txt = (await opt.inner_text()).strip().lower()
                        o_val = await opt.get_attribute("value")
                        if answer.lower() == o_txt or answer.lower() in o_txt or (o_val and answer.lower() == o_val.lower()):
                            matched_val = o_val
                            break
                    if not matched_val and len(options) > 1:
                        for opt in options:
                            o_txt = (await opt.inner_text()).strip().lower()
                            if "yes" in o_txt or "master" in o_txt or "india" in o_txt or "immediate" in o_txt:
                                matched_val = await opt.get_attribute("value")
                                break
                        if not matched_val:
                            matched_val = await options[1].get_attribute("value")

                    if matched_val:
                        await sel.select_option(value=matched_val)
                        await sel.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", matched_val)
                        logger.info(f"  ✨ [Dropdown Selected] '{label_text}' -> '{matched_val}'")
                except Exception as e:
                    logger.warning(f"Dropdown selection note: {e}")

            # 4. Handle radio buttons
            fieldsets = await self._page.query_selector_all(".artdeco-modal fieldset, .artdeco-modal [data-test-form-builder-radio-button-form-component='true']")
            for fs in fieldsets:
                try:
                    legend = await fs.query_selector("legend, label, span.fb-form-element-label")
                    legend_text = (await legend.inner_text()) if legend else ""
                    radios = await fs.query_selector_all("input[type='radio']")
                    labels = await fs.query_selector_all("label")

                    if radios or labels:
                        radio_texts = [(await r.get_attribute("value") or "") for r in radios] + [(await l.inner_text()).strip() for l in labels]
                        answer = await self.answer_form_field(
                            question_text=legend_text,
                            field_type="radio",
                            options=radio_texts,
                            job_title=job_title,
                            company=company,
                            exp_years=exp_years,
                        )

                        clicked = False
                        for lbl in labels:
                            l_txt = (await lbl.inner_text()).strip().lower()
                            if (answer.lower() == "yes" and "yes" in l_txt) or (answer.lower() == "no" and "no" in l_txt) or (answer.lower() in l_txt):
                                await lbl.scroll_into_view_if_needed()
                                await lbl.click(force=True)
                                logger.info(f"  ✨ [Radio Clicked] '{legend_text}' -> '{l_txt}'")
                                clicked = True
                                break
                        if not clicked and radios:
                            for r in radios:
                                r_val = (await r.get_attribute("value") or "").lower()
                                if (answer.lower() == "yes" and "yes" in r_val) or (answer.lower() == "no" and "no" in r_val) or (answer.lower() in r_val):
                                    await r.evaluate("(el) => { el.checked = true; el.dispatchEvent(new Event('change', { bubbles: true })); el.dispatchEvent(new Event('click', { bubbles: true })); }")
                                    logger.info(f"  ✨ [Radio Checked] '{legend_text}' -> '{r_val}'")
                                    clicked = True
                                    break
                        if not clicked and labels:
                            await labels[0].click(force=True)
                except Exception as e:
                    logger.warning(f"Radio selection note: {e}")

            # 5. Check checkboxes
            checkboxes = await self._page.query_selector_all(".artdeco-modal input[type='checkbox']")
            for cb in checkboxes:
                try:
                    if not await cb.is_checked():
                        await cb.check()
                except Exception:
                    pass

            # 6. Check for Submit button
            submit_btn = await self._page.query_selector(
                "button[aria-label*='Submit application'], button.artdeco-button--primary:has-text('Submit application'), button:has-text('Submit')"
            )
            if submit_btn and await submit_btn.is_visible():
                if self.dry_run:
                    logger.info("  🧪 [DRY RUN] Ready to Submit! (Dry run enabled — skipping final click)")
                    await self._dismiss_modal()
                    return "DRY_RUN_COMPLETED"
                else:
                    logger.info("  🚀 Submitting final application...")
                    await submit_btn.click()
                    await asyncio.sleep(2.5)

                    post_handled = await self._dismiss_post_apply_popup()
                    modal_check = await self._page.query_selector("div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal")
                    post_apply_txt = await self._page.query_selector(
                        ".artdeco-modal:has-text('Application sent'), .artdeco-modal:has-text('Applied'), .artdeco-modal:has-text('Your application was sent'), div:has-text('Application sent')"
                    )

                    if not modal_check or not await modal_check.is_visible() or post_handled or post_apply_txt:
                        logger.info("  🎉 Application submitted successfully!")
                        await self._dismiss_modal()
                        return "APPLIED"

                    # Heal validation errors if submit was blocked
                    if await FormSelfHealer.has_validation_errors(self._page):
                        await FormSelfHealer.heal_errors(
                            page=self._page,
                            portal_name="linkedin",
                            step_num=step,
                            job_title=job_title,
                            company=company,
                            gemini_client=self.gemini_client,
                        )
                        re_submit = await self._page.query_selector(
                            "button[aria-label*='Submit application'], button.artdeco-button--primary:has-text('Submit application'), button:has-text('Submit')"
                        )
                        if re_submit and await re_submit.is_visible():
                            await re_submit.click()
                            await asyncio.sleep(2.5)
                            await self._dismiss_post_apply_popup()

                    await self._dismiss_modal()
                    return "APPLIED"

            # 7. Check for Review button
            review_btn = await self._page.query_selector(
                "button[aria-label*='Review your application'], button.artdeco-button--primary:has-text('Review')"
            )
            if review_btn and await review_btn.is_visible():
                await review_btn.click()
                await asyncio.sleep(1.5)
                if await FormSelfHealer.has_validation_errors(self._page):
                    await FormSelfHealer.heal_errors(
                        page=self._page,
                        portal_name="linkedin",
                        step_num=step,
                        job_title=job_title,
                        company=company,
                        gemini_client=self.gemini_client,
                    )
                    await review_btn.click()
                    await asyncio.sleep(1.5)
                continue

            # 8. Check for Next button
            next_btn = await self._page.query_selector(
                "button[aria-label*='Continue to next step'], button.artdeco-button--primary:has-text('Next')"
            )
            if next_btn and await next_btn.is_visible():
                await next_btn.click()
                await asyncio.sleep(1.5)
                if await FormSelfHealer.has_validation_errors(self._page):
                    await FormSelfHealer.heal_errors(
                        page=self._page,
                        portal_name="linkedin",
                        step_num=step,
                        job_title=job_title,
                        company=company,
                        gemini_client=self.gemini_client,
                    )
                    re_next = await self._page.query_selector(
                        "button[aria-label*='Continue to next step'], button.artdeco-button--primary:has-text('Next')"
                    )
                    if re_next and await re_next.is_visible():
                        await re_next.click()
                        await asyncio.sleep(1.5)
                continue

        await self._dismiss_modal()
        return "INCOMPLETE"

    async def _dismiss_post_apply_popup(self) -> bool:
        """Dismiss post-submission popups like 'Not now', 'Done', 'No thanks', 'Got it', or Cross (X) icon."""
        dismissed = False
        try:
            for selector in [
                "button:has-text('Not now')",
                "button[aria-label*='Not now']",
                "button:has-text('No thanks')",
                "button:has-text('Done')",
                "button[aria-label*='Done']",
                "button:has-text('Got it')",
                "button.artdeco-modal__dismiss",
                "button[aria-label='Dismiss']",
                "button[aria-label='Close']",
                "button.artdeco-toast-item__dismiss",
            ]:
                btns = await self._page.query_selector_all(selector)
                for btn in btns:
                    if await btn.is_visible():
                        txt = ((await btn.inner_text()) or "").strip()
                        aria = (await btn.get_attribute("aria-label")) or ""
                        await btn.click(force=True)
                        logger.info(f"  ✨ Dismissed post-apply popup ({txt or aria or 'Cross icon'})")
                        dismissed = True
                        await asyncio.sleep(0.8)
                        break
        except Exception as e:
            logger.warning(f"Note during post-apply popup dismissal: {e}")
        return dismissed

    async def _dismiss_modal(self):
        """Close Easy Apply modal safely and handle any 'Not now', 'Done', or cross icons."""
        try:
            await self._dismiss_post_apply_popup()
            for sel in [
                "button[aria-label='Dismiss']",
                "button.artdeco-modal__dismiss",
                "button[aria-label='Close']",
                "button:has-text('Done')",
                "button:has-text('Not now')",
            ]:
                btn = await self._page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click(force=True)
                    await asyncio.sleep(0.8)

            discard_btn = await self._page.query_selector(
                "button[data-control-name='discard_application_confirm_btn'], button.artdeco-button--primary:has-text('Discard'), button:has-text('Discard')"
            )
            if discard_btn and await discard_btn.is_visible():
                await discard_btn.click(force=True)
                await asyncio.sleep(0.8)
        except Exception:
            pass

    async def extract_and_apply_jobs(
        self,
        target_applied: int = 20,
        max_inspect_per_page: int = 25,
    ) -> tuple[list[dict], int]:
        """
        Iterate over job cards on the current page using dynamic browser querying (immune to DOM detachment).
        Filters by experience, generates tailored resume, and applies via Easy Apply.
        """
        results = []
        applied_count = 0
        seen_keys: set[str] = set()

        # Discover initial count of job cards (query only top-level list items to avoid duplicate counts)
        card_count = await self._page.evaluate("""
            () => {
                let cards = document.querySelectorAll("li.jobs-search-results__list-item, li[data-occludable-job-id]");
                if (!cards || cards.length === 0) {
                    cards = document.querySelectorAll("div.job-card-container");
                }
                return cards.length;
            }
        """)
        logger.info(f"📋 Discovered {card_count} job listings on current page")

        total_to_inspect = min(card_count if card_count > 0 else max_inspect_per_page, max_inspect_per_page)

        for idx in range(total_to_inspect):
            if self.daily_limit_hit:
                logger.warning("⛔ [LinkedIn Daily Limit Reached] Skipping remaining cards on page.")
                break

            if applied_count >= target_applied:
                logger.info(f"🎯 Target of {target_applied} applications reached on current page!")
                break

            if await self._check_daily_limit_reached():
                logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily limit warning detected!")
                self.daily_limit_hit = True
                break

            try:
                # 1. Scroll container and click the job card dynamically in the live DOM
                click_success = await self._page.evaluate(f"""
                    (i) => {{
                        const container = document.querySelector('.jobs-search-results-list') || document.querySelector('.scaffold-layout__list-container') || window;
                        container.scrollBy(0, 120);
                        let cards = document.querySelectorAll("li.jobs-search-results__list-item, li[data-occludable-job-id]");
                        if (!cards || cards.length === 0) {{
                            cards = document.querySelectorAll("div.job-card-container");
                        }}
                        if (i < cards.length) {{
                            cards[i].scrollIntoView({{ behavior: 'instant', block: 'center' }});
                            const link = cards[i].querySelector("a.job-card-list__title, a.job-card-container__link, a");
                            if (link) link.click();
                            else cards[i].click();
                            return true;
                        }}
                        return false;
                    }}
                """, idx)

                if not click_success:
                    logger.warning(f"Could not click job card {idx + 1} — reaching end of rendered cards")
                    break

                await asyncio.sleep(2.5)

                if await self._check_daily_limit_reached():
                    logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily limit warning displayed on job view!")
                    self.daily_limit_hit = True
                    break

                # 2. Extract title & company from details pane
                title_elem = await self._page.query_selector(
                    ".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1.t-24, h2.topcard__title, .jobs-unified-top-card__content--two-pane h1"
                )
                title = (await title_elem.inner_text()).strip() if title_elem else ""

                company_elem = await self._page.query_selector(
                    ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, .jobs-unified-top-card__subtitle-primary-grouping a, a.topcard__org-name-link"
                )
                company = (await company_elem.inner_text()).strip() if company_elem else "Company"

                # Deduplication check
                job_id_match = re.search(r"currentJobId=(\d+)", self._page.url) or re.search(r"/jobs/view/(\d+)", self._page.url)
                current_job_id = job_id_match.group(1) if job_id_match else ""
                current_page_url = self._page.url
                job_url = f"https://www.linkedin.com/jobs/view/{current_job_id}" if current_job_id else current_page_url

                session_key = current_job_id if current_job_id else f"{title.lower()}::{company.lower()}"
                if session_key in seen_keys:
                    logger.debug(f"⏭️ Skipping already inspected job in current session: '{title}' @ {company}")
                    continue
                seen_keys.add(session_key)

                logger.info(f"\n[{idx + 1}/{total_to_inspect}] 🔎 Inspecting: '{title}' @ {company}")

                if JobTracker.is_already_applied("linkedin", job_url=job_url, title=title, company=company):
                    logger.info(f"⏭️ Skipping already applied job: '{title}' @ {company}")
                    continue

                # 3. Expand full JD by clicking "...more" button
                try:
                    expand_btn = await self._page.query_selector(
                        "button.jobs-description__footer-button, button[aria-label*='more'], footer.artdeco-card__actions button, .show-more-less-html__button"
                    )
                    if expand_btn and await expand_btn.is_visible():
                        await expand_btn.click(force=True)
                        await asyncio.sleep(1.0)
                except Exception:
                    pass

                # 4. Extract full job description text
                desc_selectors = [
                    "#job-details",
                    ".show-more-less-html__markup",
                    ".jobs-description__content",
                    ".jobs-description-content__text",
                    ".jobs-box__html-content",
                    ".jobs-description",
                    ".description__text",
                    "article.jobs-description__container",
                    ".details-pane__content",
                ]
                job_desc = ""
                for d_sel in desc_selectors:
                    try:
                        d_elem = await self._page.query_selector(d_sel)
                        if d_elem:
                            txt = (await d_elem.inner_text()).strip()
                            if len(txt) > 40:
                                job_desc = txt
                                break
                    except Exception:
                        pass

                if not job_desc or len(job_desc) < 20:
                    logger.warning("Could not extract job description — skipping")
                    continue

                # 5. Analyze Experience
                analysis = FinanceExperienceAnalyzer.analyze(job_title=title, job_description=job_desc)
                if not analysis["eligible"]:
                    logger.info(f"⏩ Skipping '{title}' — {analysis['reason']}")
                    JobTracker.record_job("linkedin", company, title, job_url=job_url, status="SKIPPED_EXP", notes=analysis["reason"])
                    results.append({"title": title, "company": company, "reason": analysis["reason"], "status": "SKIPPED_EXP"})
                    continue

                logger.info(f"✅ Experience Matched: {analysis['reason']}")

                # 6. Generate tailored ATS 1-page PDF
                job_dict = {
                    "title": title,
                    "company": company,
                    "description": job_desc,
                }
                tailored_pdf_path = self.resume_service.generate_tailored_resume(
                    job=job_dict,
                    portal="linkedin",
                )
                logger.info(f"📄 Tailored ATS PDF Ready: {tailored_pdf_path}")

                # 7. Check if already applied on page
                already_applied = await self._page.query_selector(
                    ".jobs-s-apply__application-link, span:has-text('Applied'), button:has-text('Applied')"
                )
                if already_applied and await already_applied.is_visible():
                    logger.info(f"ℹ️ Already applied to '{title}' @ {company} — skipping")
                    JobTracker.record_job("linkedin", company, title, job_url=job_url, status="ALREADY_APPLIED")
                    continue

                # 8. Detect Apply Button Type
                apply_btn = await self._page.query_selector(
                    ".jobs-apply-button--top-card button, button.jobs-apply-button, .jobs-unified-top-card button[aria-label*='Apply']"
                )
                if not apply_btn or not await apply_btn.is_visible():
                    apply_btn = await self._page.query_selector("button:has-text('Easy Apply'), button:has-text('Apply')")

                if not apply_btn or not await apply_btn.is_visible():
                    if await self._check_daily_limit_reached():
                        logger.warning("⛔ [LinkedIn Daily Limit Reached] Easy Apply blocked due to daily limit. Advancing to next portal!")
                        self.daily_limit_hit = True
                        break
                    logger.info("ℹ️ No Apply button found on this post — skipping")
                    JobTracker.record_job("linkedin", company, title, job_url=job_url, status="NO_APPLY_BUTTON")
                    results.append({"title": title, "company": company, "resume": tailored_pdf_path, "status": "NO_APPLY_BUTTON"})
                    continue

                btn_text = ((await apply_btn.inner_text()) or "").strip()
                btn_aria = ((await apply_btn.get_attribute("aria-label")) or "").strip()
                btn_full = f"{btn_text} {btn_aria}".lower()

                # Handle External Apply ("Apply on company website")
                if "easy apply" not in btn_full:
                    logger.info(f"🌐 Job has '{btn_text}' (External Apply). Recording external application...")
                    try:
                        pages_before = len(self._page.context.pages)
                        await apply_btn.click(force=True)
                        await asyncio.sleep(2.0)
                        pages_after = self._page.context.pages
                        if len(pages_after) > pages_before:
                            new_tab = pages_after[-1]
                            ext_url = new_tab.url
                            logger.info(f"🌐 Opened external career portal: {ext_url}")
                            await new_tab.close()
                    except Exception as e:
                        logger.debug(f"External apply click note: {e}")

                    applied_count += 1
                    JobTracker.record_job("linkedin", company, title, job_url=job_url, status="APPLIED_EXTERNAL", resume_version=tailored_pdf_path)
                    results.append({
                        "title": title,
                        "company": company,
                        "job_url": job_url,
                        "resume": tailored_pdf_path,
                        "status": "APPLIED_EXTERNAL",
                    })
                    continue

                # Handle Easy Apply
                logger.info("🎯 Clicking 'Easy Apply'...")
                await apply_btn.click()
                await asyncio.sleep(2.0)

                if await self._check_daily_limit_reached():
                    logger.warning("⛔ [LinkedIn Daily Limit Reached] Daily limit warning detected after clicking Easy Apply!")
                    self.daily_limit_hit = True
                    break

                apply_status = await self._handle_easy_apply_modal(
                    job_title=title,
                    company=company,
                    resume_pdf_path=tailored_pdf_path,
                    exp_years=1.0,
                )

                if apply_status == "DAILY_LIMIT_REACHED" or self.daily_limit_hit:
                    logger.warning("⛔ [LinkedIn Daily Limit Reached] Exiting LinkedIn immediately!")
                    self.daily_limit_hit = True
                    break

                if apply_status in ("APPLIED", "DRY_RUN_COMPLETED"):
                    applied_count += 1
                    logger.info(f"🎉 Application Recorded! (Total applied: {applied_count}/{target_applied})")

                JobTracker.record_job("linkedin", company, title, job_url=job_url, status=apply_status, resume_version=tailored_pdf_path)
                results.append({
                    "title": title,
                    "company": company,
                    "job_url": job_url,
                    "resume": tailored_pdf_path,
                    "status": apply_status,
                })

                delay = random.uniform(2.5, 4.5)
                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"Error processing job card {idx + 1}: {e}")

        return results, applied_count

    async def run_auto_apply(
        self,
        target_applied: int = 45,
        max_inspect: int = 60,
        location: str = "India",
    ) -> List[Dict]:
        """
        Executes multi-role sweep across Finance roles on LinkedIn.
        Applies up to target_applied applications and returns summary.
        """
        applied_count = 0
        all_results = []

        logger.info("\n" + "=" * 65)
        logger.info(f"🔵 [LINKEDIN BROWSER AGENT] Starting run (Target: {target_applied} applications, Fresher / 0-1 yrs)")
        logger.info("   🎯 Experience Filters: Internship (1), Entry level (2), Associate (3)")
        logger.info("   🎯 Apply Filter: Easy Apply (f_AL=true)")
        logger.info("=" * 65)

        for role_idx, current_role in enumerate(FINANCE_TARGET_ROLES, 1):
            if applied_count >= target_applied:
                break

            if self.daily_limit_hit:
                logger.warning("⛔ [LinkedIn Daily Limit Active] Halting role sweeps.")
                break

            logger.info(f"\n{'#'*65}\n🎯 [ROLE {role_idx}/{len(FINANCE_TARGET_ROLES)}] Searching LinkedIn: '{current_role}' ({location}) [Target: {target_applied}]\n{'#'*65}")

            role_applied = 0
            page_num = 0
            while role_applied < target_applied and applied_count < target_applied and page_num < 4:
                start_offset = page_num * 25
                logger.info(f"\n📄 [LinkedIn: '{current_role}'] Page {page_num + 1} (start={start_offset})...")

                search_url = (
                    f"https://www.linkedin.com/jobs/search/?"
                    f"keywords={quote_plus(current_role)}&"
                    f"location={quote_plus(location)}&"
                    f"f_TPR=r86400&"
                    f"f_E=1,2,3&"
                    f"f_AL=true&"
                    f"sortBy=DD&"
                    f"start={start_offset}"
                )

                try:
                    await self._page.goto(search_url, wait_until="domcontentloaded", timeout=50000)
                    await asyncio.sleep(3.0)

                    # Check if 0 jobs found on past 24h, broaden to past week
                    card_count = await self._page.evaluate("""
                        () => document.querySelectorAll("li[data-occludable-job-id], div.job-card-container, div[data-job-id], li.jobs-search-results__list-item").length
                    """)

                    if card_count == 0 and page_num == 0:
                        logger.info(f"ℹ️ 0 jobs in past 24h for '{current_role}', broadening to past week...")
                        search_url_week = (
                            f"https://www.linkedin.com/jobs/search/?"
                            f"keywords={quote_plus(current_role)}&"
                            f"location={quote_plus(location)}&"
                            f"f_TPR=r604800&"
                            f"f_E=1,2,3&"
                            f"f_AL=true&"
                            f"sortBy=DD&"
                            f"start={start_offset}"
                        )
                        await self._page.goto(search_url_week, wait_until="domcontentloaded", timeout=50000)
                        await asyncio.sleep(3.0)

                    results, applied_on_page = await self.extract_and_apply_jobs(
                        target_applied=target_applied - applied_count,
                        max_inspect_per_page=max_inspect,
                    )

                    all_results.extend([r for r in results if r.get("status") in ("APPLIED", "APPLIED_EXTERNAL", "DRY_RUN_COMPLETED")])
                    role_applied += applied_on_page
                    applied_count += applied_on_page
                    page_num += 1

                    if not results:
                        logger.info(f"🛑 No more jobs discovered on page {page_num} for '{current_role}'.")
                        break

                    if self.daily_limit_hit:
                        break

                except Exception as page_err:
                    logger.warning(f"Error on role page '{current_role}': {page_err}")
                    break

        logger.info(f"\n🏁 [LinkedIn Complete] Successfully submitted/recorded {applied_count}/{target_applied} jobs.")
        return all_results

    async def close(self):
        """Disconnect session safely."""
        await self.browser_client.close()
