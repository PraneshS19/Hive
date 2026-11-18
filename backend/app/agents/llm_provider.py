import json
import re
import time
from typing import Any

import httpx
from app.core.config import settings
from app.core.logging import logger
from pydantic import BaseModel


class LocalLLMProvider:
    """
    Local-first LLM provider using Ollama.
    Strictly local, zero cloud/paid APIs, zero API key dependencies.
    Uses Ollama's local chat/generate API with think=False and format=json for fast,
    reliable, structured inference.
    Gracefully falls back to deterministic rules if Ollama is unreachable, times out,
    or returns invalid outputs.
    """

    def __init__(self):
        self.enabled = settings.OLLAMA_ENABLED
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model = settings.OLLAMA_MODEL
        self.timeout = settings.OLLAMA_TIMEOUT_SECONDS
        self._last_health_check: float = 0.0
        self._is_healthy: bool = False

    async def is_available(self, force_check: bool = False) -> bool:
        """
        Check if Ollama is running and the configured model is installed.
        Caches health status for 5 seconds to reduce unnecessary socket overhead.
        """
        if not self.enabled:
            return False

        now = time.time()
        if not force_check and (now - self._last_health_check) < 5.0:
            return self._is_healthy

        self._last_health_check = now
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    payload = res.json()
                    models = [m.get("name", "") for m in payload.get("models", [])]
                    # Check exact match or base match (e.g., qwen3.5:4b or qwen3.5:4b-latest)
                    model_found = any(self.model in m or m.startswith(self.model) for m in models)
                    if not model_found:
                        logger.warning(
                            f"Ollama server is active but configured model '{self.model}' is not in installed models: {models}"
                        )
                        self._is_healthy = False
                        return False
                    self._is_healthy = True
                    return True
                self._is_healthy = False
                return False
        except httpx.HTTPError as e:
            logger.debug(f"Ollama health check unreachable: {e}")
            self._is_healthy = False
            return False

    def clean_json_string(self, raw_text: str) -> str:
        """Clean markdown codeblocks, whitespace, or commentary around a JSON payload."""
        text = raw_text.strip()
        # Remove ```json ... ``` code fence if present
        if "```" in text:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if match:
                text = match.group(1).strip()
        # Find outer braces { ... }
        start_idx = text.find("{")
        end_idx = text.rfind("}")
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            text = text[start_idx : end_idx + 1]
        return text

    async def generate_structured(
        self,
        prompt: str,
        system_prompt: str,
        expected_keys: list | None = None,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.1,
        num_predict: int = 250,
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """
        Request structured JSON from the configured local Ollama model.
        Returns: (parsed_dict, provenance_metadata)
        provenance_metadata contains:
          - provider: 'ollama' | 'deterministic_fallback'
          - model: str | None
          - execution_mode: 'local_llm' | 'deterministic_fallback'
          - latency_ms: float
          - validation_passed: bool
          - error: Optional[str]
        """
        t0 = time.time()
        meta: dict[str, Any] = {
            "provider": "deterministic_fallback",
            "model": None,
            "execution_mode": "deterministic_fallback",
            "latency_ms": 0.0,
            "validation_passed": False,
            "error": None,
        }

        if not self.enabled:
            meta["error"] = "Ollama is disabled in configuration"
            return None, meta

        is_up = await self.is_available()
        if not is_up:
            meta["error"] = f"Ollama is unreachable or model '{self.model}' is not installed"
            return None, meta

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a quantitative financial assistant in HIVE, an educational paper-trading simulator. "
                        f"{system_prompt}. "
                        "You MUST respond ONLY with a valid JSON object. Do not include markdown codeblocks, extraneous thoughts, or commentary."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                elapsed_ms = round((time.time() - t0) * 1000.0, 1)
                meta["latency_ms"] = elapsed_ms

                if response.status_code != 200:
                    meta["error"] = f"Ollama returned HTTP status {response.status_code}: {response.text[:100]}"
                    return None, meta

                resp_json = response.json()
                raw_content = resp_json.get("message", {}).get("content", "")
                if not raw_content:
                    # Fallback check for response field if /api/generate was used
                    raw_content = resp_json.get("response", "")

                cleaned = self.clean_json_string(raw_content)
                parsed = json.loads(cleaned)

                if not isinstance(parsed, dict) or not parsed:
                    meta["error"] = f"Model output is not a valid JSON dictionary: {cleaned[:80]}"
                    return None, meta

                # Validate expected keys if specified
                if expected_keys:
                    missing = [k for k in expected_keys if k not in parsed]
                    if missing:
                        meta["error"] = f"Missing required keys in model output: {missing}"
                        return None, meta

                # Validate with Pydantic model if specified
                if schema_model:
                    try:
                        schema_model.model_validate(parsed)
                    except (TypeError, ValueError) as val_err:
                        meta["error"] = f"Pydantic schema validation error: {val_err}"
                        return None, meta

                # Successfully validated inference
                meta["provider"] = "ollama"
                meta["model"] = self.model
                meta["execution_mode"] = "local_llm"
                meta["validation_passed"] = True
                return parsed, meta

        except httpx.TimeoutException:
            elapsed_ms = round((time.time() - t0) * 1000.0, 1)
            meta["latency_ms"] = elapsed_ms
            meta["error"] = f"Ollama request timed out after {self.timeout}s"
            logger.warning(f"Local LLM timeout on prompt for {self.model}: {meta['error']}")
            return None, meta
        except json.JSONDecodeError as j_err:
            elapsed_ms = round((time.time() - t0) * 1000.0, 1)
            meta["latency_ms"] = elapsed_ms
            meta["error"] = f"Failed to parse JSON from model: {j_err}"
            logger.warning(f"Malformed JSON from local LLM: {j_err}")
            return None, meta
        except (httpx.HTTPError, TypeError, ValueError, KeyError, AttributeError) as e:
            elapsed_ms = round((time.time() - t0) * 1000.0, 1)
            meta["latency_ms"] = elapsed_ms
            meta["error"] = f"Unexpected error during Ollama inference: {e}"
            logger.warning(f"Ollama generation failed: {e}")
            return None, meta


local_llm_provider = LocalLLMProvider()
