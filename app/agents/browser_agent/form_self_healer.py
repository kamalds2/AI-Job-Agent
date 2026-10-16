"""
Universal Form Self-Healing & Visual Screenshot Diagnostic Engine for Finance Job Board Agents.
Automatically detects form validation errors (e.g. number constraints, missing selections,
unsupported text like 'Immediate' where integer is expected), captures diagnostic screenshots
in 'screenshots/form_errors/', and dynamically heals the form using rule-based heuristics & Gemini Vision.
Works across LinkedIn, Indeed, Cutshort, Hirist, and Y Combinator auto-apply agents.
"""
import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_LOCATION,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
)

logger = logging.getLogger(__name__)

SCREENSHOTS_DIR = Path("screenshots/form_errors")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


class FormSelfHealer:
    """Self-healing form validator with visual screenshot diagnostics and multimodal recovery."""

    ERROR_SELECTORS = [
        ".artdeco-inline-feedback--error",
        ".artdeco-inline-feedback__message",
        ".fb-form-element-label__error",
        "[aria-invalid='true']",
        "div.ia-Questions-itemError",
        "div.css-1h9q2w9",
        ".invalid-feedback",
        ".form-error",
        ".error-message",
        "div[class*='error']",
        "span[class*='Error']",
        "p[class*='error']",
    ]

    @classmethod
    async def capture_diagnostic_screenshot(
        cls,
        page,
        portal_name: str,
        step_num: int,
        job_title: str = "",
    ) -> str:
        """Capture and save a diagnostic screenshot of the failing form modal/page."""
        timestamp = int(time.time())
        clean_title = re.sub(r"[^\w]", "_", (job_title or "job").lower())[:25]
        filename = f"{portal_name.lower()}_{clean_title}_step{step_num}_{timestamp}.png"
        file_path = SCREENSHOTS_DIR / filename

        try:
            modal = await page.query_selector(
                "div[data-test-modal], .jobs-easy-apply-modal, .artdeco-modal, div.ia-BasePage, div.slider_container, div[role='dialog']"
            )
            if modal and await modal.is_visible():
                await modal.screenshot(path=str(file_path))
            else:
                await page.screenshot(path=str(file_path), full_page=False)

            logger.info(f"📸 [Screenshot Diagnostic] Saved error screenshot to: {file_path}")
            return str(file_path)
        except Exception as e:
            logger.warning(f"Could not capture diagnostic screenshot: {e}")
            return ""

    @classmethod
    async def has_validation_errors(cls, container) -> bool:
        """Check if any validation error indicators are currently visible in the container/page."""
        for sel in cls.ERROR_SELECTORS:
            try:
                elems = await container.query_selector_all(sel)
                for el in elems:
                    if await el.is_visible():
                        txt = (await el.inner_text()).strip()
                        if txt:
                            return True
            except Exception:
                pass
        return False

    @classmethod
    async def heal_errors(
        cls,
        page,
        portal_name: str,
        step_num: int,
        job_title: str = "",
        company: str = "",
        gemini_client=None,
    ) -> bool:
        """
        Detect any validation errors on the current form step, capture screenshot,
        auto-fix invalid inputs (e.g. converting 'Immediate' to '0' when numbers are required),
        and return True if healing was performed.
        """
        containers = [page] + page.frames
        active_error_found = False

        for container in containers:
            if await cls.has_validation_errors(container):
                active_error_found = True
                break

        if not active_error_found:
            return False

        # 1. Capture Diagnostic Screenshot
        screenshot_path = await cls.capture_diagnostic_screenshot(
            page=page,
            portal_name=portal_name,
            step_num=step_num,
            job_title=job_title,
        )

        logger.info(f"🛠️ [Self-Healer] Activating automated error recovery for Step {step_num} ({job_title})...")

        # 2. Find and heal erroneous inputs across main page and frames
        healed_count = 0

        for container in containers:
            try:
                invalid_inputs = await container.query_selector_all(
                    "input[aria-invalid='true'], select[aria-invalid='true'], textarea[aria-invalid='true'], input.artdeco-inline-feedback--error, div.artdeco-inline-feedback--error input, div.ia-Questions-itemError input, div.ia-Questions-itemError select, [data-test-form-element-error='true'] input, [data-test-form-element-error='true'] select"
                )

                all_text_inputs = await container.query_selector_all(
                    "input[type='text'], input[type='number'], input[type='tel'], input:not([type]), textarea, select"
                )
                candidate_inputs = list(invalid_inputs)
                for inp in all_text_inputs:
                    if inp not in candidate_inputs:
                        has_err = await inp.evaluate("""
                            (el) => {
                                const parent = el.closest('.fb-form-element, .artdeco-inline-feedback, .ia-Questions-item, div.artdeco-form__group, div');
                                if (!parent) return false;
                                return !!parent.querySelector('.artdeco-inline-feedback--error, .fb-form-element-label__error, .ia-Questions-itemError, [aria-invalid="true"], [data-test-form-element-error]');
                            }
                        """)
                        if has_err:
                            candidate_inputs.append(inp)

                for inp in candidate_inputs:
                    tag_name = await inp.evaluate("(el) => el.tagName.toLowerCase()")
                    inp_type = (await inp.get_attribute("type") or "text").lower()
                    current_val = (await inp.input_value()) if (tag_name == "input" or tag_name == "textarea") else ""

                    id_attr = await inp.get_attribute("id") or ""
                    label_text = ""
                    if id_attr:
                        lbl_elem = await container.query_selector(f"label[for='{id_attr}']")
                        if lbl_elem:
                            label_text = await lbl_elem.inner_text()
                    if not label_text:
                        label_text = (await inp.get_attribute("aria-label")) or (await inp.get_attribute("placeholder")) or ""
                    if not label_text:
                        label_text = await inp.evaluate("""
                            (el) => {
                                const p = el.closest('.fb-form-element, .artdeco-inline-feedback, .ia-Questions-item, div.artdeco-form__group, div');
                                return p ? (p.querySelector('label, legend, span, h3')?.innerText || '') : '';
                            }
                        """)

                    q_lower = label_text.lower()
                    logger.info(f"  🔍 [Self-Healer] Erroneous Field Detected: '{label_text}' (Current value: '{current_val}')")

                    # HEALING RULE 1: Notice Period numeric constraint
                    if "notice" in q_lower or "how soon" in q_lower or "joining" in q_lower or "period" in q_lower:
                        if tag_name == "select":
                            options = await inp.query_selector_all("option")
                            for opt in options:
                                o_txt = (await opt.inner_text()).lower()
                                o_val = await opt.get_attribute("value")
                                if any(kw in o_txt for kw in ["immediate", "0-15", "0 to 15", "15 days", "0 days", "0", "15"]):
                                    await inp.select_option(value=o_val)
                                    await inp.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", o_val)
                                    break
                        else:
                            new_val = "0"
                            await inp.fill(new_val)
                            logger.info(f"  ✨ [Self-Healer] Corrected Notice Period '{current_val}' -> '{new_val}' (Numeric '0' days constraint satisfied)")
                        healed_count += 1
                        continue

                    # HEALING RULE 2: Current CTC (1.8 LPA / 180000)
                    if "current" in q_lower and any(w in q_lower for w in ["salary", "ctc", "compensation", "package", "drawn", "earnings"]):
                        if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs", "lac"]):
                            new_val = "1.8"
                        elif any(w in q_lower for w in ["monthly", "per month"]):
                            new_val = "15000"
                        else:
                            new_val = "180000"

                        if tag_name == "select":
                            options = await inp.query_selector_all("option")
                            for opt in options:
                                o_txt = (await opt.inner_text()).lower()
                                o_val = await opt.get_attribute("value")
                                if any(kw in o_txt for kw in ["1.8", "1-2", "0-2", "1 to 2", "less than 2", "< 2", "180000"]):
                                    await inp.select_option(value=o_val)
                                    await inp.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", o_val)
                                    break
                        else:
                            await inp.fill(new_val)
                        logger.info(f"  ✨ [Self-Healer] Corrected Current CTC '{current_val}' -> '{new_val}'")
                        healed_count += 1
                        continue

                    # HEALING RULE 3: Expected CTC (4.5 LPA / 450000)
                    if ("expected" in q_lower or "desired" in q_lower) and any(w in q_lower for w in ["salary", "ctc", "compensation", "package"]):
                        if any(w in q_lower for w in ["in lakh", "in lpa", "in lac", "lpa", "lakhs", "lacs", "lac"]):
                            new_val = "4.5"
                        elif any(w in q_lower for w in ["monthly", "per month"]):
                            new_val = "35000"
                        else:
                            new_val = "450000"

                        if tag_name == "select":
                            options = await inp.query_selector_all("option")
                            for opt in options:
                                o_txt = (await opt.inner_text()).lower()
                                o_val = await opt.get_attribute("value")
                                if any(kw in o_txt for kw in ["4.5", "4-5", "4 to 5", "3-5", "450000", "4.5 lpa"]):
                                    await inp.select_option(value=o_val)
                                    await inp.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", o_val)
                                    break
                        else:
                            await inp.fill(new_val)
                        logger.info(f"  ✨ [Self-Healer] Corrected Expected CTC '{current_val}' -> '{new_val}'")
                        healed_count += 1
                        continue

                    # HEALING RULE 4: Years of experience numeric constraint (0-1 yrs)
                    if "experience" in q_lower or "years" in q_lower or "how many" in q_lower:
                        new_val = "1"
                        if tag_name == "select":
                            options = await inp.query_selector_all("option")
                            for opt in options:
                                o_txt = (await opt.inner_text()).lower()
                                o_val = await opt.get_attribute("value")
                                if "1" in o_txt or "0-1" in o_txt or "fresher" in o_txt or "yes" in o_txt:
                                    await inp.select_option(value=o_val)
                                    await inp.evaluate("(el, val) => { el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", o_val)
                                    break
                        else:
                            await inp.fill(new_val)
                        logger.info(f"  ✨ [Self-Healer] Corrected Experience '{current_val}' -> '{new_val}' (Fresher / 0-1 yrs)")
                        healed_count += 1
                        continue

                    # HEALING RULE 5: Phone numbers
                    if "phone" in q_lower or "mobile" in q_lower or "contact" in q_lower or inp_type == "tel":
                        new_val = CANDIDATE_PHONE.replace("+91-", "").replace("+91", "").strip()
                        await inp.fill(new_val)
                        logger.info(f"  ✨ [Self-Healer] Corrected Phone -> '{new_val}'")
                        healed_count += 1
                        continue

                    # HEALING RULE 6: GPA / Percentage
                    if "gpa" in q_lower or "percentage" in q_lower or "marks" in q_lower:
                        new_val = "75" if ("percentage" in q_lower or "%" in q_lower) else "7.5"
                        await inp.fill(new_val)
                        logger.info(f"  ✨ [Self-Healer] Corrected GPA/Percentage -> '{new_val}'")
                        healed_count += 1
                        continue

                    # HEALING RULE 7: Generic number constraint
                    if inp_type == "number" or "number" in q_lower or "whole number" in q_lower or "integer" in q_lower:
                        digits = re.sub(r"[^\d]", "", current_val)
                        new_val = digits if digits else "0"
                        await inp.fill(new_val)
                        logger.info(f"  ✨ [Self-Healer] Coerced value to valid integer '{current_val}' -> '{new_val}'")
                        healed_count += 1
                        continue

                    # HEALING RULE 8: Default Yes/1
                    if not current_val or current_val.lower() in ("unknown", "none", ""):
                        new_val = "Yes"
                        await inp.fill(new_val)
                        healed_count += 1

            except Exception as e:
                logger.warning(f"Error during field healing: {e}")

        # 3. Handle unselected Radios & Checkboxes across containers
        for container in containers:
            try:
                fieldsets = await container.query_selector_all("fieldset, div[data-test-form-builder-radio-button-form-component], div.ia-Questions-item, div.artdeco-form__group")
                for fs in fieldsets:
                    radios = await fs.query_selector_all("input[type='radio']")
                    labels = await fs.query_selector_all("label")
                    if radios:
                        is_any_checked = any([await r.is_checked() for r in radios])
                        if not is_any_checked:
                            clicked = False
                            for lbl in labels:
                                l_txt = (await lbl.inner_text()).strip().lower()
                                if "yes" in l_txt:
                                    await lbl.scroll_into_view_if_needed()
                                    await lbl.click(force=True)
                                    logger.info(f"  ✨ [Self-Healer] Clicked 'Yes' radio label: '{l_txt}'")
                                    clicked = True
                                    healed_count += 1
                                    break
                            if not clicked and labels:
                                await labels[0].scroll_into_view_if_needed()
                                await labels[0].click(force=True)
                                logger.info("  ✨ [Self-Healer] Clicked first radio label")
                                healed_count += 1

                checkboxes = await container.query_selector_all("input[type='checkbox']")
                for cb in checkboxes:
                    if not await cb.is_checked():
                        await cb.check()
                        logger.info("  ✨ [Self-Healer] Checked required confirmation checkbox")
                        healed_count += 1
            except Exception as e:
                logger.warning(f"Radio/checkbox healing note: {e}")

        # 4. Multimodal AI Vision Fallback if screenshot available and gemini_client configured
        if healed_count == 0 and screenshot_path and os.path.exists(screenshot_path) and gemini_client:
            try:
                logger.info("🧠 [Self-Healer] Invoking Gemini Vision Multimodal to analyze error screenshot...")
                vision_prompt = (
                    f"Look at this screenshot of a job application form with validation errors for job '{job_title}' at '{company}'.\n"
                    f"Candidate Profile: Doddi Kamal Kumar, Software Engineer / Java Backend & AI Developer, B.Tech CSE (2024, 8.0 CGPA), 1.5 - 2 years experience with Java, Spring Boot, Microservices, Python, AI Agents, AWS, Docker. Current CTC: 3.5 LPA (350000 INR), Expected CTC: 7.0 LPA (700000 INR), Notice Period: 0 days (immediate joiner), India citizen, Open to relocation/hybrid/remote.\n"
                    f"Rules:\n"
                    f"- If question asks Notice Period in days or requires whole number -> 0\n"
                    f"- If question asks Current CTC in lakhs -> 3.5, in raw integer -> 350000\n"
                    f"- If question asks Expected CTC in lakhs -> 7.0, in raw integer -> 700000\n"
                    f"- If radio or dropdown is missing selection -> select 'Yes' or appropriate option.\n"
                    f"Identify what exact values should be entered in the failing/red input fields.\n"
                    f"Return ONLY a JSON list of fixes: [{{\"field_text\": \"...\", \"fix_value\": \"...\"}}]"
                )
                if hasattr(gemini_client, "generate_vision_content"):
                    vision_resp = gemini_client.generate_vision_content(
                        prompt=vision_prompt,
                        image_path=screenshot_path,
                        json_mode=True,
                    )
                else:
                    vision_resp = gemini_client.generate_content(
                        prompt=vision_prompt,
                        json_mode=True,
                    )

                if vision_resp:
                    clean_resp = vision_resp.strip()
                    if "```json" in clean_resp:
                        clean_resp = clean_resp.split("```json")[1].split("```")[0].strip()
                    elif "```" in clean_resp:
                        clean_resp = clean_resp.split("```")[1].split("```")[0].strip()
                    fixes = json.loads(clean_resp)
                    if isinstance(fixes, list):
                        for item in fixes:
                            f_txt = item.get("field_text", "").lower()
                            f_val = str(item.get("fix_value", "Yes"))
                            for inp in all_text_inputs:
                                id_a = await inp.get_attribute("id") or ""
                                if f_txt in id_a.lower() or f_txt in (await inp.get_attribute("aria-label") or "").lower():
                                    await inp.fill(f_val)
                                    logger.info(f"  ✨ [Vision-Healer] Applied AI fix '{f_val}' to field '{f_txt}'")
                                    healed_count += 1
            except Exception as e:
                logger.warning(f"Vision fallback note: {e}")

        logger.info(f"✅ [Self-Healer] Form healing completed ({healed_count} fields adjusted). Ready to proceed!")
        await asyncio.sleep(1.0)
        return True
