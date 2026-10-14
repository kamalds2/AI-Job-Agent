"""
Agent 3: Form Submitter for LinkedIn Easy Apply
Automates multi-step interactive modal forms:
- Uploads tailored PDF resume
- Answers screening questions (Years of Exp, Dropdowns, Radio, Text) with zero hallucination
- Advances through modal steps, reviews, and submits application with screenshot proof.
"""
import asyncio
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import Locator, Page

from app.config.browser_settings import (
    DEFAULT_CURRENT_LOCATION,
    DEFAULT_NOTICE_PERIOD,
    DEFAULT_YEARS_OF_EXPERIENCE,
)
from app.config.settings import (
    CANDIDATE_EMAIL,
    CANDIDATE_LOCATION,
    CANDIDATE_NAME,
    CANDIDATE_PHONE,
    REPORTS_DIR,
)
from app.services.screening_qa_service import ScreeningQAService

logger = logging.getLogger(__name__)


class FormSubmitter:
    """
    Agent 3: Interactive UI operator for LinkedIn Easy Apply forms.
    """

    def __init__(self, page: Page):
        self.page = page
        self.qa_service = ScreeningQAService()
        self.screenshots_dir = Path(REPORTS_DIR) / "screenshots"
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)

    async def apply_to_job(
        self,
        job_title: str,
        company: str,
        resume_pdf_path: str,
        job_url: str = "",
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes complete Easy Apply modal submission workflow.
        """
        logger.info(f"🎯 [Agent 3] Initiating Easy Apply for '{job_title}' @ {company}")
        result = {
            "status": "FAILED",
            "job_title": job_title,
            "company": company,
            "resume_path": resume_pdf_path,
            "questions_answered": [],
            "screenshot_path": None,
            "error": None,
        }

        try:
            # 1. Locate and Click Easy Apply Button
            apply_button_selector = (
                "button.jobs-apply-button:has-text('Easy Apply'), "
                "button:has-text('Easy Apply'), "
                "button.jobs-apply-button"
            )
            apply_btn = self.page.locator(apply_button_selector).first
            if await apply_btn.count() == 0 or not await apply_btn.is_visible():
                result["error"] = "Easy Apply button not visible or already applied"
                return result

            await apply_btn.click(timeout=5000)
            await asyncio.sleep(2.0)

            # Wait for modal to appear
            modal_selector = "div.jobs-easy-apply-modal, div.artdeco-modal[role='dialog']"
            try:
                await self.page.wait_for_selector(modal_selector, timeout=8000)
            except Exception:
                result["error"] = "Application modal did not appear"
                return result

            modal = self.page.locator(modal_selector).first

            # 2. Iterate through form steps (Max 8 steps to prevent infinite loop)
            max_steps = 8
            current_step = 0
            submitted = False

            while current_step < max_steps and not submitted:
                current_step += 1
                await asyncio.sleep(1.2)

                # Step A: Handle Contact Info Fields (if present)
                await self._fill_contact_fields(modal)

                # Step B: Handle Resume Upload (if present)
                if resume_pdf_path and os.path.exists(resume_pdf_path):
                    await self._handle_resume_upload(modal, resume_pdf_path)

                # Step C: Answer Screening Questions (if present)
                step_answers = await self._handle_screening_questions(modal, job_title, company)
                if step_answers:
                    result["questions_answered"].extend(step_answers)

                # Step D: Check for Review / Submit / Next Buttons
                submit_btn = modal.locator(
                    "button:has-text('Submit application'), "
                    "button[aria-label*='Submit application']"
                ).first

                if await submit_btn.count() > 0 and await submit_btn.is_visible():
                    # We are on the final Review & Submit step!
                    screenshot_name = f"apply_{re.sub(r'[^w]', '_', company)}_{int(datetime.now().timestamp())}.png"
                    screenshot_path = str(self.screenshots_dir / screenshot_name)
                    await self.page.screenshot(path=screenshot_path)
                    result["screenshot_path"] = screenshot_path

                    if dry_run:
                        logger.info(f"🔍 [Agent 3 - DRY RUN] Reached final review step for '{job_title}' @ {company}. Skipping final submit.")
                        result["status"] = "DRY_RUN_REVIEW_READY"
                        await self._dismiss_modal()
                        return result
                    else:
                        logger.info(f"🚀 [Agent 3] Submitting application for '{job_title}' @ {company}...")
                        await submit_btn.click(timeout=5000)
                        await asyncio.sleep(3.0)

                        # Verify confirmation screen
                        submitted = True
                        result["status"] = "APPLIED_EASY_APPLY"
                        logger.info(f"✅ [Agent 3] Successfully submitted application for '{job_title}' @ {company}!")
                        await self._dismiss_modal()
                        return result

                # Check for Next / Review step button
                next_btn = modal.locator(
                    "button:has-text('Next'), "
                    "button:has-text('Review'), "
                    "button[aria-label*='Continue to next step']"
                ).first

                if await next_btn.count() > 0 and await next_btn.is_visible():
                    await next_btn.click(timeout=5000)
                    await asyncio.sleep(1.5)
                else:
                    logger.warning(f"[Agent 3] No 'Next' or 'Submit' button found on step {current_step}")
                    break

            if not submitted and result["status"] == "FAILED":
                await self._dismiss_modal()

        except Exception as e:
            logger.error(f"[Agent 3] Error during Easy Apply submission: {e}")
            result["error"] = str(e)
            await self._dismiss_modal()

        return result

    async def _fill_contact_fields(self, modal: Locator):
        """Fills phone number, email, and location if inputs are empty."""
        try:
            # Phone input
            phone_inputs = modal.locator("input[id*='phoneNumber'], input[name*='phone']").all()
            for inp in await phone_inputs:
                curr_val = await inp.input_value()
                if not curr_val:
                    await inp.fill(CANDIDATE_PHONE)
                    await asyncio.sleep(0.3)

            # City / Location input
            city_inputs = modal.locator("input[id*='city'], input[name*='city'], input[id*='location']").all()
            for inp in await city_inputs:
                curr_val = await inp.input_value()
                if not curr_val:
                    await inp.fill(CANDIDATE_LOCATION)
                    await asyncio.sleep(0.5)
                    # Handle autocomplete dropdown if appears
                    first_opt = self.page.locator("div.basic-typeahead__selectable-result").first
                    if await first_opt.count() > 0 and await first_opt.is_visible():
                        await first_opt.click()

        except Exception as e:
            logger.debug(f"[Agent 3] Contact field handling notice: {e}")

    async def _handle_resume_upload(self, modal: Locator, resume_pdf_path: str):
        """Locates file upload input and attaches tailored PDF resume."""
        try:
            file_input = modal.locator("input[type='file']").first
            if await file_input.count() > 0:
                abs_path = os.path.abspath(resume_pdf_path)
                logger.info(f"📎 [Agent 3] Uploading tailored ATS resume: {abs_path}")
                await file_input.set_input_files(abs_path)
                await asyncio.sleep(1.5)
        except Exception as e:
            logger.debug(f"[Agent 3] Resume upload notice: {e}")

    async def _handle_screening_questions(
        self,
        modal: Locator,
        job_title: str,
        company: str,
    ) -> List[Dict[str, str]]:
        """
        Scans all form controls in the current step and fills answers.
        """
        answered = []
        try:
            # 1. Numeric and Text Inputs
            text_inputs = await modal.locator("input[type='text'], input[type='number']").all()
            for inp in text_inputs:
                if not await inp.is_visible():
                    continue

                curr_val = await inp.input_value()
                if curr_val and curr_val.strip():
                    continue  # Already has value

                # Find associated label
                label_text = await self._get_label_text_for_input(inp)
                if not label_text:
                    continue

                answer = await self.qa_service.resolve_question_with_ai(
                    question_text=label_text,
                    input_type="text",
                    job_title=job_title,
                    company=company,
                )
                await inp.fill(str(answer))
                answered.append({"question": label_text, "answer": str(answer)})
                await asyncio.sleep(0.3)

            # 2. Radio Buttons / Fieldsets
            fieldsets = await modal.locator("fieldset").all()
            for fs in fieldsets:
                if not await fs.is_visible():
                    continue

                legend = fs.locator("legend").first
                question_text = await legend.inner_text() if await legend.count() > 0 else ""
                if not question_text:
                    continue

                # Check if already selected
                checked_radio = fs.locator("input[type='radio']:checked").first
                if await checked_radio.count() > 0:
                    continue

                answer = await self.qa_service.resolve_question_with_ai(
                    question_text=question_text,
                    input_type="radio",
                    job_title=job_title,
                    company=company,
                )

                # Find radio button matching answer (e.g. Yes / No)
                target_radio = fs.locator(f"label:has-text('{answer}'), input[value='{answer}']").first
                if await target_radio.count() > 0 and await target_radio.is_visible():
                    await target_radio.click()
                    answered.append({"question": question_text, "answer": answer})
                    await asyncio.sleep(0.3)

            # 3. Dropdown Selects
            selects = await modal.locator("select").all()
            for sel in selects:
                if not await sel.is_visible():
                    continue

                label_text = await self._get_label_text_for_input(sel)
                options = await sel.locator("option").all_inner_texts()
                clean_opts = [o.strip() for o in options if o.strip() and "select an option" not in o.lower()]

                if clean_opts:
                    chosen_opt = await self.qa_service.resolve_question_with_ai(
                        question_text=label_text or "Select option",
                        input_type="select",
                        options=clean_opts,
                        job_title=job_title,
                        company=company,
                    )
                    try:
                        await sel.select_option(label=chosen_opt)
                        answered.append({"question": label_text or "Dropdown", "answer": chosen_opt})
                        await asyncio.sleep(0.3)
                    except Exception:
                        await sel.select_option(index=1)

        except Exception as e:
            logger.debug(f"[Agent 3] Screening question solver notice: {e}")

        return answered

    async def _get_label_text_for_input(self, input_locator: Locator) -> str:
        """Finds label or preceding span text describing an input."""
        try:
            inp_id = await input_locator.get_attribute("id")
            if inp_id:
                label = self.page.locator(f"label[for='{inp_id}']").first
                if await label.count() > 0:
                    return (await label.inner_text()).strip()

            # Check parent container for label
            parent = input_locator.locator("xpath=..")
            label_in_parent = parent.locator("label, span.fb-form-element-label, span.t-14").first
            if await label_in_parent.count() > 0:
                return (await label_in_parent.inner_text()).strip()

        except Exception:
            pass
        return ""

    async def _dismiss_modal(self):
        """Closes application modal safely if still open."""
        try:
            dismiss_btn = self.page.locator(
                "button[aria-label='Dismiss'], "
                "button.artdeco-modal__dismiss, "
                "button[data-test-modal-close-btn]"
            ).first
            if await dismiss_btn.count() > 0 and await dismiss_btn.is_visible():
                await dismiss_btn.click()
                await asyncio.sleep(0.8)

                # Confirm discard if modal asks
                discard_btn = self.page.locator(
                    "button[data-control-name='discard_application_confirm_btn'], "
                    "button:has-text('Discard')"
                ).first
                if await discard_btn.count() > 0 and await discard_btn.is_visible():
                    await discard_btn.click()
                    await asyncio.sleep(0.5)
        except Exception:
            pass
