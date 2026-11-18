import asyncio
import json
import re
import time
from typing import Any

import httpx
from app.core.config import settings
from app.core.logging import logger
from pydantic import BaseModel


class ReviewModelClient:
    """
    Unified multi-model client for sequential execution and independent review
    supporting Qwen3.5 4B (executor) and Gemma 3 4B (reviewer / improvement analyst).
    Enforces sequential VRAM lifecycle management, truthful error reporting,
    and explicit unavailable states.
    """

    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.executor_model = settings.HIVE_EXECUTOR_MODEL
        self.reviewer_model = settings.HIVE_REVIEWER_MODEL
        self.timeout = settings.HIVE_MODEL_TIMEOUT_SECONDS
        self.keep_alive = settings.HIVE_MODEL_KEEP_ALIVE
        self.enabled = settings.OLLAMA_ENABLED
        self._inference_lock = asyncio.Lock()

    @staticmethod
    def _model_key(name: str) -> str:
        tag = name if ":" in name.rsplit("/", 1)[-1] else f"{name}:latest"
        return tag.casefold()

    async def _installed_models(self, client: httpx.AsyncClient) -> dict[str, dict]:
        response = await client.get(f"{self.base_url}/api/tags", timeout=4.0)
        response.raise_for_status()
        models = response.json()["models"]
        if not isinstance(models, list):
            raise TypeError("Invalid Ollama model list")
        installed = {}
        for entry in models:
            name = entry.get("name") or entry.get("model")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("Invalid Ollama model name")
            installed[self._model_key(name)] = {"name": name, "digest": entry.get("digest")}
        return installed

    async def get_model_status(self) -> dict[str, Any]:
        available = False
        models = {}
        message = "Ollama integration disabled by configuration"
        if self.enabled:
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    models = await self._installed_models(client)
                available = True
                message = "Ollama connected"
            except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError):
                message = "Ollama is unreachable or returned an invalid model list"

        executor_installed = self._model_key(self.executor_model) in models
        reviewer_installed = self._model_key(self.reviewer_model) in models
        missing = [model for model, installed in (
            (self.executor_model, executor_installed), (self.reviewer_model, reviewer_installed)
        ) if not installed]
        if available and missing:
            message = "Required models are missing"
        return {
            "ollama_available": available,
            "ollama_reachable": available,
            "base_url": self.base_url,
            "executor_model": self.executor_model,
            "reviewer_model": self.reviewer_model,
            "executor_installed": executor_installed,
            "reviewer_installed": reviewer_installed,
            "executor_model_installed": executor_installed,
            "reviewer_model_installed": reviewer_installed,
            "installed_models": [model["name"] for model in models.values()],
            "pull_commands": [f"ollama pull {model}" for model in missing] if available else [],
            "vram_management": f"Sequential inference (keep_alive: {self.keep_alive})",
            "status_message": message,
            "ready": available and executor_installed and reviewer_installed,
        }

    def clean_json_string(self, raw_text: str) -> str:
        """Clean markdown codeblocks, whitespace, or thinking tokens around JSON."""
        text = raw_text.strip()
        # Strip thinking tags if present (<think>...</think>)
        text = re.sub(r"<think>[\s\S]*?</think>", "", text).strip()
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
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        schema_model: type[BaseModel] | None = None,
        temperature: float = 0.1,
        num_predict: int = 500,
        keep_alive: str | None = None
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        """
        Execute structured LLM inference against the specified local Ollama model.
        Returns: (parsed_dict, telemetry)
        telemetry contains:
          - provider: 'ollama' | 'unavailable'
          - model: str
          - execution_mode: 'local_llm' | 'unavailable'
          - latency_ms: float
          - schema_validated: bool
          - error: Optional[str]
          - prompt_tokens: int
          - completion_tokens: int
        """
        t0 = time.monotonic()
        telemetry: dict[str, Any] = {
            "provider": "unavailable",
            "model": model_name,
            "execution_mode": "unavailable",
            "latency_ms": 0.0,
            "schema_validated": False,
            "error": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        if not self.enabled:
            telemetry["error"] = "Ollama is disabled in configuration"
            return None, telemetry

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{system_prompt}. "
                        "Respond strictly with a valid JSON object matching the requested schema. "
                        "Do not output markdown blocks, conversational preamble, or explanations outside the JSON."
                    )
                },
                {"role": "user", "content": user_prompt}
            ],
            "format": schema_model.model_json_schema() if schema_model else "json",
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive if keep_alive is None else keep_alive,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            }
        }

        try:
            async with self._inference_lock:
                async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
                    models = await self._installed_models(client)
                    installed = models.get(self._model_key(model_name))
                    if installed is None:
                        telemetry["error"] = f"Model unavailable. Run: ollama pull {model_name}"
                        return None, telemetry
                    telemetry["model_digest"] = installed["digest"]
                    telemetry["provider"] = "ollama"
                    telemetry["execution_mode"] = "local_llm_failed"
                    res = await client.post(f"{self.base_url}/api/chat", json=payload)
                elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
                telemetry["latency_ms"] = elapsed_ms

                if res.status_code != 200:
                    telemetry["error"] = f"Ollama HTTP {res.status_code}"
                    return None, telemetry

                res_json = res.json()
                telemetry["prompt_tokens"] = res_json.get("prompt_eval_count", 0)
                telemetry["completion_tokens"] = res_json.get("eval_count", 0)

                raw_content = res_json.get("message", {}).get("content", "")
                if not raw_content.strip():
                    telemetry["error"] = "Ollama returned empty response content"
                    return None, telemetry

                cleaned_json = self.clean_json_string(raw_content)
                parsed = json.loads(cleaned_json)
                if not isinstance(parsed, dict):
                    raise TypeError("Expected a JSON object")

                # Validate against Pydantic schema if provided
                if schema_model:
                    validated_obj = schema_model.model_validate(parsed)
                    parsed = validated_obj.model_dump()
                    telemetry["schema_validated"] = True

                telemetry["provider"] = "ollama"
                telemetry["execution_mode"] = "local_llm"
                logger.info(f"Completed local Ollama inference for {model_name}")
                return parsed, telemetry

        except httpx.TimeoutException:
            elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
            telemetry["latency_ms"] = elapsed_ms
            telemetry["error"] = f"Inference timed out after {self.timeout}s"
            logger.warning(f"Ollama call for {model_name} timed out after {self.timeout}s")
            return None, telemetry
        except json.JSONDecodeError as jde:
            elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
            telemetry["latency_ms"] = elapsed_ms
            telemetry["error"] = f"Malformed JSON from local LLM: {jde}"
            logger.warning(f"Malformed JSON from local LLM {model_name}: {jde}")
            return None, telemetry
        except (httpx.HTTPError, ValueError, TypeError, KeyError, AttributeError) as e:
            elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
            telemetry["latency_ms"] = elapsed_ms
            telemetry["error"] = f"Ollama request or response validation failed ({type(e).__name__})"
            logger.warning(f"Ollama call failed for {model_name}: {type(e).__name__}")
            return None, telemetry


review_model_client = ReviewModelClient()
