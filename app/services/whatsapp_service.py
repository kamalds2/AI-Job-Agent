"""
WhatsApp Notification Service — sends job match alerts via WhatsApp Business API.

Uses: Meta WhatsApp Business Cloud API
Docs: https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""
import logging
from typing import Optional

import httpx

from app.config.settings import (
    WHATSAPP_TOKEN,
    WHATSAPP_PHONE_ID,
    WHATSAPP_TO_NUMBER,
    DRY_RUN,
)
from app.prompts.email_prompt import WHATSAPP_NOTIFICATION_TEMPLATE

logger = logging.getLogger(__name__)

WHATSAPP_API_URL = "https://graph.facebook.com/v19.0/{phone_id}/messages"


class WhatsAppService:
    """
    Sends WhatsApp messages using Meta's Cloud API.
    """

    def __init__(self):
        self.token = WHATSAPP_TOKEN
        self.phone_id = WHATSAPP_PHONE_ID
        self.to_number = WHATSAPP_TO_NUMBER

    def _is_configured(self) -> bool:
        return all([self.token, self.phone_id, self.to_number])

    def send_message(self, message: str) -> bool:
        """Send a plain text WhatsApp message."""
        if DRY_RUN:
            logger.info(f"[DRY RUN] WhatsApp message:\n{message}")
            return True

        if not self._is_configured():
            logger.warning("WhatsApp not configured — skipping notification")
            return False

        try:
            url = WHATSAPP_API_URL.format(phone_id=self.phone_id)
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json={
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": self.to_number,
                    "type": "text",
                    "text": {"preview_url": False, "body": message},
                },
                timeout=10,
            )
            response.raise_for_status()
            logger.info("📱 WhatsApp message sent")
            return True

        except Exception as e:
            logger.error(f"❌ WhatsApp send failed: {e}")
            return False

    def send_job_match_alert(
        self,
        title: str,
        company: str,
        score: int,
        url: str,
        reasoning: str,
        email_sent: bool = False,
        resume_generated: bool = False,
    ) -> bool:
        """Send a formatted job match notification."""
        message = WHATSAPP_NOTIFICATION_TEMPLATE.format(
            title=title,
            company=company,
            score=score,
            url=url,
            reasoning=reasoning,
            email_status="sent ✅" if email_sent else "pending ⏳",
            resume_status="generated ✅" if resume_generated else "pending ⏳",
        )
        return self.send_message(message)

    def send_daily_summary(self, summary: dict) -> bool:
        """
        Send a daily summary message.
        summary = {
            "date": str,
            "total_fetched": int,
            "new_jobs": int,
            "qualified": int,
            "emails_sent": int,
            "top_jobs": list[dict]
        }
        """
        top_jobs_text = ""
        for i, job in enumerate(summary.get("top_jobs", [])[:5], 1):
            top_jobs_text += (
                f"\n{i}. *{job['title']}* @ {job['company']} — {job['score']}/100"
            )

        message = (
            f"🤖 *AI Job Agent — Daily Report* 📊\n"
            f"📅 Date: {summary.get('date', 'N/A')}\n\n"
            f"🔍 Jobs Fetched: {summary.get('total_fetched', 0)}\n"
            f"🆕 New Jobs: {summary.get('new_jobs', 0)}\n"
            f"⭐ Qualified (≥{summary.get('threshold', 65)}): {summary.get('qualified', 0)}\n"
            f"📧 Emails Sent: {summary.get('emails_sent', 0)}\n"
            f"📄 Resumes Made: {summary.get('resumes_generated', 0)}\n"
            f"\n🏆 *Top Matches:*{top_jobs_text if top_jobs_text else ' None today'}\n\n"
            f"⏰ Next run in 6 hours."
        )

        return self.send_message(message)
