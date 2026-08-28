"""
Gemini Client — Direct integration with Google Gemini API.
Supports gemini-2.0-flash, gemini-2.5-flash, gemini-1.5-flash, gemini-1.5-pro, etc.
Uses httpx with SSL flexibility for Windows, with support for system prompts and JSON schema output.
"""
import json
import logging
import sys
from typing import Optional, Any

import httpx

from app.config.settings import GEMINI_API_KEY, GEMINI_MODEL

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiClient:
    """Client for Google Gemini REST API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or GEMINI_API_KEY
        self.model = model or GEMINI_MODEL or "gemini-2.0-flash"
        # Windows SSL compatibility
        verify_ssl = False if sys.platform == "win32" else True
        self._http_client = httpx.Client(verify=verify_ssl, timeout=60.0)

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate_content(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
        model_override: Optional[str] = None,
    ) -> Optional[str]:
        """
        Generate content using Gemini API.
        
        Args:
            prompt: User message / prompt
            system_instruction: Optional system instruction prompt
            json_mode: If True, instructs Gemini to return application/json
            temperature: Sampling temperature (0.0 - 1.0)
            max_output_tokens: Max tokens to generate
            model_override: Specific model name to use instead of default
            
        Returns:
            Generated text content or None if generation failed
        """
        if not self.is_configured:
            logger.warning("Gemini API key is not configured.")
            return None

        model_name = model_override or self.model
        # Strip potential "models/" prefix if user included it
        if model_name.startswith("models/"):
            model_name = model_name.replace("models/", "")

        url = f"{GEMINI_BASE_URL}/{model_name}:generateContent?key={self.api_key}"

        payload: dict[str, Any] = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"

        import time

        for attempt in range(1, 4):
            try:
                response = self._http_client.post(url, json=payload)
                if response.status_code == 200:
                    data = response.json()
                    candidates = data.get("candidates", [])
                    if not candidates:
                        logger.warning(f"[Gemini] No candidates returned: {data}")
                        return None

                    content_parts = candidates[0].get("content", {}).get("parts", [])
                    if not content_parts:
                        logger.warning("[Gemini] Empty parts in response")
                        return None

                    text = "".join(part.get("text", "") for part in content_parts)
                    return text.strip()

                if response.status_code in (429, 503) and attempt < 3:
                    sleep_time = attempt * 1.5
                    logger.info(f"[Gemini] {response.status_code} received, retrying in {sleep_time}s (attempt {attempt}/3)...")
                    time.sleep(sleep_time)
                    continue

                logger.warning(
                    f"[Gemini] API error ({response.status_code}): {response.text[:300]}"
                )
                return None

            except Exception as e:
                if attempt < 3:
                    time.sleep(1.5)
                    continue
                logger.warning(f"[Gemini] Request failed for model '{model_name}': {e}")
                return None

        return None


def get_gemini_client() -> Optional[GeminiClient]:
    """Helper factory to obtain a configured GeminiClient instance."""
    client = GeminiClient()
    if client.is_configured:
        return client
    return None
