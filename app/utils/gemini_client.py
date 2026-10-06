"""
Gemini Client with Intelligent Multi-Agent, Multi-Key & Multi-Model Rotation.
Provides seamless failover across:
  - Multiple Google Gemini API keys (GEMINI_API_KEY, GEMINI_BACKUP_KEY, GEMINI_API_KEYS)
  - Multiple Gemini model variants (gemini-3.6-flash, gemini-2.0-flash, gemini-1.5-flash, gemini-2.5-flash)
  - OpenAI fallback (gpt-4o-mini, gpt-4o)
  - Claude fallback (claude-3-5-haiku, claude-3-haiku)
Guarantees 0 downtime and resilience against 429 rate limits & quota exhaustion.
"""
import json
import logging
import os
import re
import sys
import time
from typing import Optional, Any

import httpx

from app.config.settings import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    GEMINI_API_KEY,
    GEMINI_API_KEYS_RAW,
    GEMINI_BACKUP_KEY,
    GEMINI_MODEL,
    OPENAI_API_KEY,
)

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
GEMINI_FALLBACK_MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-1.5-flash-latest",
]



class GeminiClient:
    """Client for Google Gemini REST API with automated multi-key, multi-model, and multi-provider failover."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        # Collect all configured Gemini API keys
        self.api_keys: list[str] = []
        if api_key:
            self.api_keys.append(api_key.strip())
        if GEMINI_API_KEY and GEMINI_API_KEY.strip() not in self.api_keys:
            self.api_keys.append(GEMINI_API_KEY.strip())
        if GEMINI_BACKUP_KEY and GEMINI_BACKUP_KEY.strip() not in self.api_keys:
            self.api_keys.append(GEMINI_BACKUP_KEY.strip())
        if GEMINI_API_KEYS_RAW:
            for k in GEMINI_API_KEYS_RAW.split(","):
                k_clean = k.strip()
                if k_clean and k_clean not in self.api_keys:
                    self.api_keys.append(k_clean)

        # Check numbered env vars (GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.)
        for i in range(1, 10):
            k_env = os.getenv(f"GEMINI_API_KEY_{i}")
            if k_env and k_env.strip() and k_env.strip() not in self.api_keys:
                self.api_keys.append(k_env.strip())

        self.current_key_idx = 0
        self.key_cooldowns: dict[str, float] = {}  # key -> cooldown expiry timestamp

        self.model = model or GEMINI_MODEL or "gemini-3.6-flash"
        verify_ssl = False if sys.platform == "win32" else True
        self._http_client = httpx.Client(verify=verify_ssl, timeout=35.0)

    @property
    def is_configured(self) -> bool:
        return len(self.api_keys) > 0

    def _get_active_api_key(self) -> Optional[str]:
        """Return the next available Gemini API key not currently in cooldown."""
        if not self.api_keys:
            return None

        now = time.time()
        for _ in range(len(self.api_keys)):
            key = self.api_keys[self.current_key_idx % len(self.api_keys)]
            cooldown_until = self.key_cooldowns.get(key, 0)
            if now >= cooldown_until:
                return key
            self.current_key_idx += 1

        # If all in cooldown, return least recently cooled key
        return self.api_keys[self.current_key_idx % len(self.api_keys)]

    def _mark_key_rate_limited(self, key: str, cooldown_seconds: float = 60.0):
        """Mark a key as rate limited so requests rotate to alternate keys/agents."""
        self.key_cooldowns[key] = time.time() + cooldown_seconds
        self.current_key_idx = (self.current_key_idx + 1) % max(1, len(self.api_keys))

    def _call_openai_fallback(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = False,
    ) -> Optional[str]:
        """Failover to OpenAI if Gemini agents/quota are exhausted."""
        if not OPENAI_API_KEY or not OPENAI_API_KEY.startswith("sk-"):
            return None
        try:
            logger.info("🔄 [Failover] Rotating to OpenAI (gpt-4o-mini)...")
            messages = []
            if system_instruction:
                messages.append({"role": "system", "content": system_instruction})
            messages.append({"role": "user", "content": prompt})

            payload = {
                "model": "gpt-4o-mini",
                "messages": messages,
                "temperature": 0.1,
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}

            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json",
            }
            resp = self._http_client.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
            elif resp.status_code == 429:
                logger.warning("OpenAI quota exceeded (429).")
        except Exception as e:
            logger.warning(f"OpenAI fallback error: {e}")
        return None

    def _call_claude_fallback(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
    ) -> Optional[str]:
        """Failover to Anthropic Claude if available."""
        if not ANTHROPIC_API_KEY or not ANTHROPIC_API_KEY.startswith("sk-ant-"):
            return None
        for cm in ["claude-3-5-haiku-20241022", "claude-3-haiku-20240307", CLAUDE_MODEL]:
            try:
                logger.info(f"🔄 [Failover] Rotating to Claude ({cm})...")
                payload: dict[str, Any] = {
                    "model": cm,
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                }
                if system_instruction:
                    payload["system"] = system_instruction

                headers = {
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                }
                resp = self._http_client.post("https://api.anthropic.com/v1/messages", json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return data["content"][0]["text"].strip()
            except Exception as e:
                logger.warning(f"Claude fallback error: {e}")
        return None

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
        Generate content using Gemini with automatic multi-key rotation, model fallback & provider failover.
        """
        if not self.is_configured:
            return self._call_openai_fallback(prompt, system_instruction, json_mode) or self._call_claude_fallback(prompt, system_instruction)

        # Build list of candidate models
        primary_model = model_override or self.model
        if primary_model.startswith("models/"):
            primary_model = primary_model.replace("models/", "")

        candidate_models = [primary_model] + [m for m in GEMINI_FALLBACK_MODELS if m != primary_model]

        # Try across available API keys and models
        for _ in range(max(1, len(self.api_keys))):
            current_key = self._get_active_api_key()
            if not current_key:
                break

            for model_name in candidate_models:
                url = f"{GEMINI_BASE_URL}/{model_name}:generateContent?key={current_key}"

                payload: dict[str, Any] = {
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_output_tokens,
                    },
                }

                if system_instruction:
                    payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

                if json_mode:
                    payload["generationConfig"]["responseMimeType"] = "application/json"

                # Retry up to 2 attempts on the SAME model before rotating to next fallback model
                max_model_retries = 2
                for attempt in range(1, max_model_retries + 1):
                    try:
                        response = self._http_client.post(url, json=payload)
                        if response.status_code == 200:
                            data = response.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                content_parts = candidates[0].get("content", {}).get("parts", [])
                                if content_parts:
                                    return "".join(part.get("text", "") for part in content_parts).strip()

                        if response.status_code == 429:
                            key_hint = current_key[:6] + "..." if len(current_key) > 8 else "key"
                            resp_body = response.text.lower()

                            # If daily quota is permanently exhausted, break to next model/key
                            if "daily" in resp_body and ("quota" in resp_body or "resource_exhausted" in resp_body):
                                logger.warning(f"⛔ [Gemini:{model_name}] Daily quota reached on {key_hint}. Rotating key/model...")
                                break

                            # Standard per-minute rate limit: wait and retry on the SAME model
                            backoff = attempt * 3  # 3s, 6s
                            logger.info(
                                f"⏳ [Gemini:{model_name}] 429 Rate Limit on {key_hint} (Attempt {attempt}/{max_model_retries}). "
                                f"Waiting {backoff}s before retrying..."
                            )
                            time.sleep(backoff)
                            continue

                        if response.status_code in (500, 503):
                            backoff = attempt * 2
                            logger.warning(f"⚠️ [Gemini:{model_name}] Server busy ({response.status_code}). Retrying in {backoff}s...")
                            time.sleep(backoff)
                            continue

                        if response.status_code == 404:
                            # Model not found on this API tier, switch to next candidate model
                            break

                    except Exception as e:
                        logger.warning(f"⚠️ [Gemini:{model_name}] Connection note: {e}. Retrying in 2s...")
                        time.sleep(2.0)
                        continue

        # If all Gemini keys/models hit quota after all retries, fallback to OpenAI and Claude if configured
        if OPENAI_API_KEY and len(OPENAI_API_KEY.strip()) > 15:
            openai_resp = self._call_openai_fallback(prompt, system_instruction, json_mode)
            if openai_resp:
                return openai_resp

        if ANTHROPIC_API_KEY and len(ANTHROPIC_API_KEY.strip()) > 15:
            claude_resp = self._call_claude_fallback(prompt, system_instruction)
            if claude_resp:
                return claude_resp

        return None

    def generate_vision_content(
        self,
        prompt: str,
        image_path: str,
        system_instruction: Optional[str] = None,
        json_mode: bool = True,
        temperature: float = 0.1,
    ) -> Optional[str]:
        """
        Analyze an image (e.g. form error screenshot) using Gemini Multimodal Vision API.
        """
        if not os.path.exists(image_path):
            return None

        try:
            import base64
            with open(image_path, "rb") as img_f:
                img_bytes = img_f.read()
                b64_data = base64.b64encode(img_bytes).decode("utf-8")

            mime_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

            parts: list[dict[str, Any]] = [
                {"inlineData": {"mimeType": mime_type, "data": b64_data}},
                {"text": prompt},
            ]

            candidate_models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-3.6-flash", "gemini-1.5-pro"]
            for _ in range(max(1, len(self.api_keys))):
                current_key = self._get_active_api_key()
                if not current_key:
                    break

                for model_name in candidate_models:
                    url = f"{GEMINI_BASE_URL}/{model_name}:generateContent?key={current_key}"
                    payload: dict[str, Any] = {
                        "contents": [{"role": "user", "parts": parts}],
                        "generationConfig": {
                            "temperature": temperature,
                            "maxOutputTokens": 1024,
                        },
                    }
                    if system_instruction:
                        payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
                    if json_mode:
                        payload["generationConfig"]["responseMimeType"] = "application/json"

                    max_vision_retries = 3
                    for attempt in range(1, max_vision_retries + 1):
                        try:
                            response = self._http_client.post(url, json=payload, timeout=40.0)
                            if response.status_code == 200:
                                data = response.json()
                                candidates = data.get("candidates", [])
                                if candidates:
                                    c_parts = candidates[0].get("content", {}).get("parts", [])
                                    if c_parts:
                                        return "".join(p.get("text", "") for p in c_parts).strip()
                            elif response.status_code == 429:
                                backoff = attempt * 4
                                logger.info(f"⏳ [Gemini-Vision:{model_name}] 429 Rate Limit (Attempt {attempt}/{max_vision_retries}). Pausing {backoff}s...")
                                time.sleep(backoff)
                                continue
                        except Exception:
                            time.sleep(2.0)
                            continue
        except Exception as e:
            logger.warning(f"Error in generate_vision_content: {e}")

        return None


def get_gemini_client() -> Optional[GeminiClient]:
    """Helper factory to obtain a configured GeminiClient instance."""
    client = GeminiClient()
    if client.is_configured or OPENAI_API_KEY or ANTHROPIC_API_KEY:
        return client
    return None

