"""
LinkedIn Feed & Hiring Post Scanner -- Browser-Based Recruiter Outreach Agent.

Searches LinkedIn content per role with "hiring" keyword, Past 24h filter.
Expands each post, filters 3+ year posts, extracts emails/links,
tailors resume per JD, sends cold emails, logs links to Excel.
"""
import asyncio
import logging
import os
import re
from datetime import date, datetime
from urllib.parse import quote_plus

from app.config.settings import (
    CANDIDATE_NAME,
    EMAIL_ADDRESS,
    REPORTS_DIR,
)
from app.services.browser_tab_guard import (
    attach_context_blank_tab_monitor,
    clean_and_recover_blank_tabs,
    connect_or_launch_single_chrome,
)
from app.services.email_service import EmailService
from app.services.report_service import ReportService
from app.services.resume_service import ResumeService
from app.utils.email_validator import extract_emails_from_text

logger = logging.getLogger(__name__)

FEED_SEARCH_ROLES = [
    "Java Backend Developer",
    "Java Full Stack Developer",
    "Spring Boot Developer",
    "Java Developer",
    "Junior Software Engineer",
    "Python Backend Developer",
    "AI Agent Developer",
    "Generative AI Engineer",
    "AWS Cloud Engineer",
]

SENIOR_EXP_PATTERNS = [
    r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?)\b",
    r"\b([3-9]|\d{2,})\s*(?:to|-)\s*\d+\s*(?:years?|yrs?)\b",
    r"\b(?:minimum|at\s+least|min|requires?)\s+([3-9]|\d{2,})\s*(?:years?|yrs?)\b",
    r"\bexperience\s*:\s*([3-9]|\d{2,})\b",
    r"\b(?:senior|sr\.?|lead|principal|architect|director|vp)\s+(?:software|developer|engineer|java|python|backend|full\s*stack|cloud)\b",
    r"\b(?:looking\s+for|hiring|opening\s+for)\s+(?:a\s+)?(?:senior|sr\.?|lead|principal|architect)\b",
]

GENERIC_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "outlook.com",
    "hotmail.com", "live.com", "icloud.com", "rediffmail.com", "protonmail.com",
    "zoho.com", "aol.com", "yopmail.com", "mail.com", "gmx.com",
}

COMPANY_SUFFIX_PATTERNS = [
    (r"inc$", " Inc"),
    (r"llc$", " LLC"),
    (r"ltd$", " Ltd"),
    (r"pvt$", " Pvt"),
    (r"pvtltd$", " Pvt Ltd"),
    (r"tech$", " Tech"),
    (r"technologies$", " Technologies"),
    (r"solutions$", " Solutions"),
    (r"services$", " Services"),
    (r"systems$", " Systems"),
    (r"infotech$", " Infotech"),
    (r"corp$", " Corp"),
    (r"app$", " App"),
]

CHROME_CDP_URL = "http://127.0.0.1:9222"
AGENT_PROFILE_DATA_DIR = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\AgentProfile")
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class LinkedInFeedScanner:
    """Browser-based LinkedIn hiring post scanner and recruiter outreach agent."""

    def __init__(self):
        self.email_service = EmailService()
        self.resume_service = ResumeService()
        self.report_service = ReportService()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

    async def _connect_browser(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()

        self._context, self._page, self._is_cdp = await connect_or_launch_single_chrome(
            self._playwright,
            cdp_port=9222,
            user_data_dir=AGENT_PROFILE_DATA_DIR,
            chrome_path=CHROME_PATH,
        )

        # Rule 1: Clean any stuck about:blank / about:* tabs and attach context monitor
        self._page, _ = await clean_and_recover_blank_tabs(
            self._context,
            self._page,
            fallback_url="https://www.linkedin.com/feed/",
            allowed_domains=["linkedin.com"],
            auto_refresh=False,
        )
        attach_context_blank_tab_monitor(
            self._context,
            lambda: self._page,
            default_portal_url="https://www.linkedin.com/feed/",
            allowed_domains=["linkedin.com"],
        )

    async def _disconnect_browser(self):
        try:
            if self._context:
                for p in list(self._context.pages):
                    if p != self._page:
                        try:
                            await p.close()
                        except Exception:
                            pass
            if hasattr(self, "_is_cdp") and not self._is_cdp:
                if self._context:
                    await self._context.close()
            if self._playwright:
                await self._playwright.stop()
            logger.info("🔌 Cleanly disconnected LinkedIn feed scanner session (single Chrome preserved).")
        except Exception:
            pass

    async def _wait_for_linkedin_login(self):
        for attempt in range(120):
            try:
                url = self._page.url.lower()
                is_login = any(p in url for p in ["login", "authwall", "signup"])
                nav = await self._page.query_selector(
                    ".global-nav__me, nav.global-nav, a[href*='/feed/']")
                if nav and not is_login:
                    if attempt > 0:
                        logger.info("LinkedIn login confirmed -- resuming feed scan")
                    return
                if attempt == 0 or attempt % 20 == 0:
                    logger.info("LinkedIn sign-in required -- please log in in Chrome window")
                await asyncio.sleep(3.0)
            except Exception:
                await asyncio.sleep(2.0)

    def _is_job_seeker_post(self, text: str) -> bool:
        """Detect and skip candidate/job-seeker posts looking to get hired (e.g. #OpenToWork, 'I am looking for a job')."""
        t = text.lower()
        
        # Explicit job seeker hashtags
        seeker_hashtags = [
            "#opentowork", "#jobseeker", "#jobsearch", "#immediatejoiner",
            "#lookingforjob", "#lookingforopportunity", "#lookingforopportunities",
            "#needjob", "#hireme", "#careerchange", "#jobhunt", "#openforopportunities",
            "#careeropportunity"
        ]
        if any(h in t for h in seeker_hashtags):
            # Check if this is an employer post using hashtag, or a job-seeker
            if not any(k in t for k in ["we are hiring", "we're hiring", "our team is hiring", "urgently hiring candidates"]):
                return True

        # First-person job seeker phrases
        seeker_phrases = [
            r"\bi am looking for (?:a |an |new |entry[\s-]level )?(?:job|opportunity|role|position|opportunities)",
            r"\bi'm looking for (?:a |an |new |entry[\s-]level )?(?:job|opportunity|role|position|opportunities)",
            r"\bactively looking for (?:a |an |new |entry[\s-]level )?(?:job|opportunity|role|position|opportunities)",
            r"\bactively seeking (?:a |an |new |entry[\s-]level )?(?:job|opportunity|role|position|opportunities)",
            r"\bopen to (?:work|opportunities|new roles|entry[\s-]level)",
            r"\bseeking (?:an? )?(?:entry[\s-]level|software engineer|developer|backend|java|internship) (?:role|position|opportunity|job)",
            r"\bplease review my resume\b",
            r"\bhere is my resume\b",
            r"\bplease refer me\b",
            r"\bplease share any leads\b",
            r"\bany leads would be appreciated\b",
            r"\btransitioning from\b",
            r"\bopen to 0[–\-2]\s*yoe\b",
        ]
        for pat in seeker_phrases:
            if re.search(pat, t):
                recruiter_indicators = [
                    "we are hiring", "we're hiring", "send your resume to", "share your cv to",
                    "send your cv to", "share your resume to", "candidates can send",
                    "interested candidates can share", "drop your cv"
                ]
                if not any(ri in t for ri in recruiter_indicators):
                    return True

        return False

    def _is_senior_role(self, post_text: str) -> bool:
        text_lower = post_text.lower()
        
        # Check if explicitly early career / 0-2 yrs / fresher included (e.g. "0 to 5 years", "1 to 7 years", "0-2 YOE")
        is_early_career = bool(re.search(
            r"\b(?:0\s*(?:to|-)\s*\d+|1\s*(?:to|-)\s*\d+|2\s*(?:to|-)\s*\d+|[0-2]\s*years?|[0-2]\s*yrs?|0-2|0\+?|fresher|entry[\s-]level|intern|internship|graduate|junior|jr\.?)\b",
            text_lower
        ))
        
        # Strong senior titles in the role/headline
        if re.search(r"\b(?:senior|sr\.?|lead|principal|architect|director|head of|vp)\s+(?:software|developer|engineer|java|python|backend|full\s*stack|cloud)\b", text_lower):
            return True

        # If early career / 0-2 years is explicitly welcomed, do not discard even if upper range is higher
        if is_early_career:
            return False

        # Check for senior experience requirements (3+ years minimum required)
        for pat in [
            r"\b([3-9]|\d{2,})\s*\+\s*(?:years?|yrs?)\b",
            r"\b([3-9]|\d{2,})\s*(?:to|-)\s*\d+\s*(?:years?|yrs?)\b",
            r"\b(?:minimum|at\s+least|min|requires?)\s+([3-9]|\d{2,})\s*(?:years?|yrs?)\b",
            r"\bexperience\s*:\s*([3-9]|\d{2,})\b",
        ]:
            if re.search(pat, text_lower):
                return True
                
        return False

    def _extract_urls_from_text(self, text: str) -> list:
        return re.findall(r"https?://[^\s\)\]\>\"\']+", text)

    def _extract_company_from_email(self, email: str) -> str:
        """Extract professional company name from non-generic recruiter email domains."""
        if not email or "@" not in email:
            return ""
        domain = email.split("@")[-1].strip().lower()
        if domain in GENERIC_EMAIL_DOMAINS:
            return ""
        name_part = re.sub(r"\.(?:com|co\.in|org|net|in|io|tech|ai|biz|us|co)$", "", domain)
        if not name_part or len(name_part) < 3:
            return ""
        formatted = name_part
        for suf_pat, repl in COMPANY_SUFFIX_PATTERNS:
            if re.search(suf_pat, formatted):
                base = re.sub(suf_pat, "", formatted)
                formatted = f"{base.capitalize()}{repl}"
                return formatted
        return formatted.capitalize()

    def _extract_role_title(self, text: str, searched_role: str = "Software Engineer") -> str:
        """Extract clean developer/engineer role title, strictly filtering out reaction buttons, hashtags, and junk."""
        t = text.strip()
        role_patterns = [
            r"(?:Role|Position|Title|Profile|Designation)\s*[:\-–]\s*([A-Za-z0-9\s/+#\.\-]{3,45}?)(?:\n|,|\.|!|\|)",
            r"(?:We[’']?re\s*Hiring|Hiring|Urgent\s*Hiring)\s*\|\s*([A-Za-z0-9\s/+#\.\-]{3,45}?)\s*\|",
            r"(?:Hiring|Opening for|Looking for|Vacancy for)\s*[:\-–]?\s*(?:for\s+|a\s+|an\s+)?([A-Za-z0-9\s/+#\.\-]{3,45}?)(?:\n|at |@|\||,|\.)",
            r"\b(Java\s*(?:Full\s*Stack|Fullstack|Backend)?\s*Developer)\b",
            r"\b(Spring\s*Boot\s*(?:Developer|Engineer))\b",
            r"\b(Python\s*(?:Backend)?\s*(?:Developer|Engineer))\b",
            r"\b(Backend\s*(?:Software\s*)?(?:Developer|Engineer))\b",
            r"\b(Full\s*Stack\s*(?:Software\s*)?(?:Developer|Engineer))\b",
            r"\b(Associate\s*Software\s*Engineer)\b",
            r"\b(Software\s*(?:Development\s*)?Engineer(?:\s*[I|1|2])?)\b",
            r"\b(Cloud\s*(?:Software\s*)?Engineer)\b",
        ]

        for pat in role_patterns:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                cand = m.group(1).strip()
                cand = re.sub(r"^[^\w]+|[^\w]+$", "", cand).strip()
                cand = re.sub(r"^(?:for|a|an|the|urgent|urgently)\s+", "", cand, flags=re.IGNORECASE).strip()
                cand_lower = cand.lower()
                
                if 3 < len(cand) < 50:
                    # Reject reactions, like, comment, share, hashtags, http links
                    if any(inv in cand_lower for inv in ["reaction", "like", "comment", "share", "send", "#", "http"]):
                        continue
                    # Must contain a tech / engineering role keyword
                    if any(k in cand_lower for k in ["developer", "engineer", "architect", "programmer", "specialist", "java", "python", "backend", "full stack", "fullstack", "cloud", "software"]):
                        return cand

        return searched_role

    def _extract_company_name(self, post_text: str, poster_name: str, recruiter_email: str = None) -> str:
        """
        Extract company name using explicit post labels, 'Hiring | Role | Company' structures,
        email domains, or recruiter bio. Strictly never returns the poster's human name or 'Hiring Organization'.
        """
        # 1. Explicit labels: "Company: XYZ", "Client: XYZ", "Organization: XYZ"
        m_comp = re.search(
            r"(?:Company|Client|Organization|Organisation|Firm)\s*(?:Name)?\s*[:\-–]\s*([A-Za-z0-9&.,'\-\s]{2,40}?)(?:\n|,|\.|!|\|)",
            post_text, re.IGNORECASE
        )
        if m_comp:
            cand = m_comp.group(1).strip(" .,-")
            if 2 < len(cand) < 45 and cand.lower() not in ["hiring organization", "confidential", "na", "n/a", "none"]:
                return cand

        # 2. LinkedIn headline format: "We're Hiring | Role | Company"
        m_bar = re.search(
            r"(?:hiring|opening)\s*\|\s*[^|\n]+\|\s*([A-Za-z0-9\s&.,'-]{2,35}?)(?:\n|\?|!|\.|\|)",
            post_text, re.IGNORECASE
        )
        if m_bar:
            cand = m_bar.group(1).strip(" .,-")
            if 2 < len(cand) < 40 and not any(inv in cand.lower() for inv in ["immediate", "joiner", "hybrid", "remote", "onsite"]):
                return cand

        # 3. Post sign-off: "Regards, <Name>, <Company Solutions/Technologies>"
        m_reg = re.search(
            r"(?:Regards|Thanks|From)\s*[,:\n]+\s*(?:[A-Za-z\s.]+[,:\n]+)?([A-Za-z0-9\s&.,'-]+(?:Solutions|Technologies|Infotech|Services|Systems|Consulting|Pvt\s*Ltd|Inc|LLC|Corp|Tech|Labs))",
            post_text, re.IGNORECASE
        )
        if m_reg:
            cand = m_reg.group(1).strip(" .,-")
            if 2 < len(cand) < 45:
                return cand

        # 4. "hiring for / opening at / job at Company Name"
        m_at = re.search(
            r"(?:hiring for|opening at|job at|position at)\s+([A-Z][A-Za-z0-9\s&.,'-]{2,35}?)(?:\n|,|\.|!|\|)",
            post_text, re.IGNORECASE
        )
        if m_at:
            cand = m_at.group(1).strip(" .,-")
            if 2 < len(cand) < 40:
                return cand

        # 5. Poster affiliation: "Recruiter at XYZ", "HR at XYZ"
        if " at " in poster_name:
            org = poster_name.split(" at ")[-1].strip()
            if 2 < len(org) < 40 and org.lower() not in ["linkedin", "stealth", "none"]:
                return org
        if " @ " in poster_name:
            org = poster_name.split(" @ ")[-1].strip()
            if 2 < len(org) < 40:
                return org

        # 6. Recruiter email domain (e.g. recruiter@aaratechinc.com -> Aaratech Inc)
        if recruiter_email:
            email_comp = self._extract_company_from_email(recruiter_email)
            if email_comp:
                return email_comp

        # Return empty string if no valid company found (NEVER return poster's human name)
        return ""

    async def _scroll_until_last_post(self, max_scrolls: int = 35):
        """Continuously scroll down until the last post of the search is fetched, clicking all 'more' buttons."""
        last_count = 0
        consecutive_stalls = 0

        for scroll_idx in range(1, max_scrolls + 1):
            # 1. Click all visible 'more' / 'see more' buttons to expand post body text
            try:
                clicked = await self._page.evaluate("""
                    () => {
                        let count = 0;
                        const buttons = Array.from(document.querySelectorAll("button, span, [role='button']"));
                        for (const b of buttons) {
                            const txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                            if (txt === 'more' || txt === '… more' || txt === '... more' || txt === 'see more' || 
                                (b.className && (b.className.includes('see-more-less-toggle') || b.className.includes('show-more-text')))) {
                                if (b.offsetParent !== null && b.offsetWidth > 0) {
                                    try {
                                        b.click();
                                        count++;
                                    } catch (e) {}
                                }
                            }
                        }
                        return count;
                    }
                """)
                if clicked > 0:
                    logger.info(f"    clicked {clicked} 'more' button(s) on scroll {scroll_idx}")
            except Exception:
                pass

            # 2. Click "See more results" / "Show more results" button if present
            clicked_load_more = False
            try:
                clicked_load_more = await self._page.evaluate("""
                    () => {
                        const btn = Array.from(document.querySelectorAll("button, [role='button']")).find(b => {
                            const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                            return t === 'see more results' || t === 'show more results' || t === 'load more' || t === 'load more results';
                        });
                        if (btn && btn.offsetParent !== null && btn.offsetWidth > 0) {
                            try { btn.click(); return true; } catch(e){}
                        }
                        return false;
                    }
                """)
                if clicked_load_more:
                    logger.info(f"    clicked 'See more results' button on scroll {scroll_idx}")
            except Exception:
                pass

            # 3. Check total posts currently present in DOM
            current_count = await self._page.evaluate("""
                () => {
                    const items = document.querySelectorAll("div[role='listitem'], li[role='listitem'], [role='listitem']");
                    return items.length;
                }
            """)

            if current_count > last_count:
                consecutive_stalls = 0
                last_count = current_count
            else:
                consecutive_stalls += 1

            # 4. Check if reached bottom or 'no more results'
            is_end = await self._page.evaluate("""
                () => {
                    const bodyText = (document.body.innerText || '').toLowerCase();
                    const hasEndText = bodyText.includes("you've viewed all posts") || 
                                       bodyText.includes("no more results") || 
                                       bodyText.includes("end of results");
                    const atBottom = (window.innerHeight + window.scrollY) >= (document.body.scrollHeight - 350);
                    return hasEndText || atBottom;
                }
            """)

            if is_end and consecutive_stalls >= 3 and not clicked_load_more:
                logger.info(f"    reached the last post of search results ({current_count} total posts loaded after {scroll_idx} scrolls).")
                break

            await self._page.evaluate("window.scrollBy(0, 1500)")
            await asyncio.sleep(1.6)

    async def _search_role_hiring_posts(self, role: str) -> list:
        posts = []
        query = f'"{role}" "hiring"'
        search_url = (
            "https://www.linkedin.com/search/results/content/"
            f"?keywords={quote_plus(query)}"
            "&origin=FACETED_SEARCH"
            "&sortBy=%5B%22date_posted%22%5D"
            "&datePosted=%5B%22past-24h%22%5D"
        )
        logger.info(f"  searching: {query}")
        try:
            await self._page.goto(search_url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(4.0)
        except Exception as e:
            logger.warning(f"  navigation error for '{role}': {e}")
            return posts

        # Wait for search results container to populate in DOM
        try:
            await self._page.wait_for_selector(
                "div[role='listitem'], [role='listitem'], div.feed-shared-update-v2",
                timeout=12000,
            )
        except Exception:
            pass

        # Continuously scroll until the last post of that search is fetched & expanded
        await self._scroll_until_last_post(max_scrolls=35)

        # Extract all posts directly from page DOM in JavaScript
        raw_posts = await self._page.evaluate("""
            () => {
                const items = Array.from(document.querySelectorAll("div[role='listitem'], li[role='listitem'], [role='listitem']"));
                return items.map((el, idx) => {
                    const fullText = (el.innerText || el.textContent || '').trim();
                    const allAnchors = Array.from(el.querySelectorAll("a"));
                    const allLinks = allAnchors.map(a => a.href);
                    const mailtoLinks = allAnchors
                        .filter(a => a.href.startsWith('mailto:'))
                        .map(a => a.href.replace('mailto:', '').split('?')[0]);
                    const postLink = allLinks.find(h => h.includes('/feed/update/') || h.includes('/posts/') || h.includes('activity'));
                    const actorLink = allLinks.find(h => h.includes('/in/'));
                    
                    const actorEl = el.querySelector("span.feed-shared-actor__name, span.update-components-actor__name, [class*='actor__name'], a[href*='/in/'] span, .feed-shared-actor__sub-description");
                    const poster = actorEl ? (actorEl.innerText || actorEl.textContent || '').trim() : '';

                    const bodyEl = el.querySelector("[data-testid='expandable-text-box'], [class*='show-more-text'], div.feed-shared-inline-show-more-text, div.feed-shared-update-v2__description, div[class*='update-components-text'], p");
                    const postBody = bodyEl ? (bodyEl.innerText || bodyEl.textContent || '').trim() : '';

                    return {
                        idx,
                        fullText,
                        postBody,
                        poster,
                        actorLink: actorLink || '',
                        postLink: postLink || actorLink || window.location.href,
                        mailtoLinks,
                        allLinks
                    };
                }).filter(p => p.fullText.length > 50);
            }
        """)

        logger.info(f"  found {len(raw_posts)} raw post(s) for '{role}'")
        seen_texts: set = set()

        for p in raw_posts:
            try:
                full_text = p.get("fullText", "").strip()
                if not full_text or len(full_text) < 40:
                    continue

                fp = full_text[:90]
                if fp in seen_texts:
                    continue
                seen_texts.add(fp)

                poster_name = p.get("poster", "").strip()
                post_body = p.get("postBody", "").strip()
                analysis_text = post_body if len(post_body) > 30 else full_text

                # 1. Skip candidate/job-seeker posts looking to get hired (e.g. #OpenToWork, #JobSearch, etc.)
                if self._is_job_seeker_post(full_text):
                    logger.info(f"    skipping job-seeker/candidate post from {poster_name or 'poster'}")
                    continue

                # 2. Analyze experience requirements (skip strictly senior / 3+ years posts)
                if self._is_senior_role(analysis_text):
                    logger.info(f"    skipping senior/3+yrs post from {poster_name or 'poster'}")
                    continue

                # 3. Extract recruiter / HR email from text AND mailto links
                emails = extract_emails_from_text(full_text)
                for m in p.get("mailtoLinks", []):
                    if m and "@" in m and m.lower() not in [e.lower() for e in emails]:
                        emails.append(m.lower())
                recruiter_email = emails[0] if emails else None

                # 4. Extract application links
                body_urls = [
                    u for u in p.get("allLinks", [])
                    if "lnkd.in" in u or "linkedin.com/jobs" in u or "forms.gle" in u or "google.com/forms" in u
                    or ("apply" in u.lower() and "linkedin.com" not in u)
                    or ("careers" in u.lower())
                ][:3]

                # 5. Extract clean role title and company name
                role_title = self._extract_role_title(full_text, searched_role=role)
                company = self._extract_company_name(full_text, poster_name, recruiter_email=recruiter_email)
                post_url = p.get("postLink") or p.get("actorLink") or search_url

                # Only include posts that have an email or a direct application link
                if not emails and not body_urls:
                    logger.debug(f"    skipping post without email or application link from {poster_name}")
                    continue

                posts.append({
                    "role": role, "title": role_title, "company": company,
                    "poster": poster_name, "post_url": post_url,
                    "raw_text": full_text[:3000], "hr_email": recruiter_email,
                    "all_emails": emails, "body_urls": body_urls,
                })

                if emails:
                    comp_display = company if company else "(no company found)"
                    logger.info(f"    email found: {emails[0]} | '{role_title}' @ {comp_display}")
                elif body_urls:
                    comp_display = company if company else "(no company found)"
                    logger.info(f"    link found: {body_urls[0]} | '{role_title}' @ {comp_display}")
            except Exception as pe:
                logger.debug(f"post parse note: {pe}")

        logger.info(f"  '{role}' -> {len(posts)} eligible post(s) extracted")
        return posts

    async def scan_posts_and_outreach(
        self, roles: list = None, dry_run: bool = False, use_browser: bool = True,
    ) -> dict:
        """
        Main entry: scan LinkedIn feed per role, email recruiters with tailored resumes,
        log links to Excel, send summary email to candidate.
        """
        logger.info("starting LinkedIn feed hiring post scan")
        roles_to_scan = roles or FEED_SEARCH_ROLES
        all_posts: list = []

        if use_browser:
            await self._connect_browser()
            try:
                await self._page.goto("https://www.linkedin.com/feed/",
                                      wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(3.0)
                await self._wait_for_linkedin_login()
                for role_idx, role in enumerate(roles_to_scan, 1):
                    logger.info(f"\n[{role_idx}/{len(roles_to_scan)}] Role: {role}")
                    role_posts = await self._search_role_hiring_posts(role)
                    all_posts.extend(role_posts)
                    logger.info(f"  '{role}' -> {len(role_posts)} posts")
                    await asyncio.sleep(2.0)
            except Exception as e:
                logger.error(f"browser scan error: {e}")
            finally:
                await self._disconnect_browser()

        logger.info(f"total posts: {len(all_posts)}")

        outreach_entries: list = []
        emails_sent_count = 0
        links_found_count = 0
        seen_emails: set = set()

        resume_text = ""
        try:
            resume_text = self.resume_service.extract_resume_text()
        except Exception:
            pass

        for post in all_posts:
            title = post["title"]
            company = post["company"]
            hr_email = post.get("hr_email")
            body_urls = post.get("body_urls", [])
            post_url = post.get("post_url", "")
            raw_text = post.get("raw_text", "")
            sent = False
            resume_path = None
            if company:
                subject = f"Application: {title} at {company}"
            else:
                subject = f"Application for {title} Role"

            if hr_email and hr_email not in seen_emails:
                seen_emails.add(hr_email)
                try:
                    resume_path = self.resume_service.generate_tailored_resume(
                        job={"id": f"lnfeed_{len(outreach_entries)}", "title": title,
                             "company": company or "Target Engineering Team", "description": raw_text},
                        candidate_profile={}, exp_years=2.0, portal="linkedin_feed")
                    logger.info(f"  tailored resume: {os.path.basename(resume_path)}")
                except Exception as re_err:
                    logger.warning(f"  resume note: {re_err}")

                draft = self.email_service.draft_email(
                    job_title=title, company=company,
                    job_description=raw_text, resume_text=resume_text, match_score=90)
                cover_letter = draft.get("body", "")
                subject = draft.get("subject") or subject

                if not dry_run:
                    sent = self.email_service.send_email(
                        to_email=hr_email, subject=subject,
                        body=cover_letter, pdf_attachment_path=resume_path)
                    if sent:
                        emails_sent_count += 1
                        logger.info(f"  email sent -> {hr_email}  '{title}' @ {company or 'Direct Recruiter'}")
                else:
                    logger.info(f"  [DRY RUN] would email {hr_email}  '{title}' @ {company or 'Direct Recruiter'}")
                    sent = True

                outreach_entries.append({
                    "role_searched": post.get("role", ""),
                    "title": title, "company": company or "Direct Recruiter",
                    "route": "Stream A -- Email Outreach",
                    "hr_email": hr_email, "to_email": hr_email,
                    "post_url": post_url, "job_url": post_url,
                    "email_sent": sent, "resume_path": resume_path or "",
                    "subject": subject, "score": "90/100",
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                })

            elif body_urls and not hr_email:
                for url in body_urls:
                    links_found_count += 1
                    outreach_entries.append({
                        "role_searched": post.get("role", ""),
                        "title": title, "company": company or "Direct Recruiter",
                        "route": "Stream B -- Link Only",
                        "hr_email": "", "to_email": "",
                        "post_url": url, "job_url": url,
                        "email_sent": False, "resume_path": "",
                        "subject": "", "score": "N/A",
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    })

        run_stats = {
            "posts_scanned_for_hr": len(all_posts),
            "recruiter_emails_found": len(seen_emails),
            "emails_sent": emails_sent_count,
            "direct_applied": links_found_count,
        }
        report_path = ""
        try:
            report_path = self.report_service.generate_recruiter_report(
                recruiter_entries=outreach_entries, stats=run_stats)
            logger.info(f"Excel report: {report_path}")
        except Exception as rpe:
            logger.warning(f"report note: {rpe}")

        if EMAIL_ADDRESS and not dry_run:
            today_str = date.today().strftime("%Y-%m-%d")
            summary_subject = f"[AI Job Agent] LinkedIn Feed Outreach Report -- {today_str}"
            summary_body = (
                f"Hi {CANDIDATE_NAME},\n\n"
                f"LinkedIn Feed Scan Report for {today_str}.\n\n"
                f"Metrics:\n"
                f"- Roles searched: {len(roles_to_scan)}\n"
                f"- Total hiring posts found: {len(all_posts)}\n"
                f"- Recruiter emails discovered: {len(seen_emails)}\n"
                f"- Cold emails sent (with tailored resume): {emails_sent_count}\n"
                f"- Job links found (no email, saved to Excel): {links_found_count}\n\n"
                f"See attached Excel for full details.\n\nAI Job Agent\n"
            )
            try:
                self.email_service.send_email(
                    to_email=EMAIL_ADDRESS, subject=summary_subject, body=summary_body,
                    attachment_path=report_path if report_path and os.path.exists(report_path) else None)
                logger.info(f"summary report sent to {EMAIL_ADDRESS}")
            except Exception as mail_err:
                logger.warning(f"summary email note: {mail_err}")

        return {
            "posts_scanned": len(all_posts),
            "recruiter_emails_found": len(seen_emails),
            "emails_sent": emails_sent_count,
            "direct_links_prepared": links_found_count,
            "report_path": report_path,
        }

    async def open_login_window(self):
        """Open a browser window to let the user log in to LinkedIn and save the session."""
        from playwright.async_api import async_playwright
        os.makedirs(AGENT_PROFILE_DATA_DIR, exist_ok=True)
        print("Opening LinkedIn login window...")
        async with async_playwright() as p:
            try:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=AGENT_PROFILE_DATA_DIR,
                    executable_path=CHROME_PATH,
                    headless=False,
                    args=["--start-maximized"])
            except Exception:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=AGENT_PROFILE_DATA_DIR, headless=False)
            page = await context.new_page()
            await page.goto("https://www.linkedin.com/login")
            try:
                await page.wait_for_url("**/feed/**", timeout=120000)
                print("Login successful! Session saved.")
            except Exception:
                print("Browser closed. Session preserved.")
            await context.close()
