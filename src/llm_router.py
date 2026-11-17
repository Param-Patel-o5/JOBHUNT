"""
Multi-Model Rate-Limit Safe LLM Router with Round-Robin Multi-Key Pool.

Features:
  - Multi-account round-robin key cycling across GEMINI_API_KEYS.
  - Automatic quota (429 / ResourceExhausted) failover to next key in pool.
  - Immediate model fallback on 503 / UNAVAILABLE / ServerError / timeout (max_retries=1, timeout=20).
  - Model downgrade fallback chain if all keys are exhausted for a model.
  - Tier-based RPM pacing (1.2s for lite, 3.5s for smart).
"""

import os
import re
import time
import logging
import threading
from typing import Type, TypeVar, List, Dict, Any, Optional, Tuple, Union

from dotenv import load_dotenv
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

logger = logging.getLogger("llm_router")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

T = TypeVar("T", bound=BaseModel)

# Confirmed-working models only (2026-11):
# - gemini-2.5-flash-lite  → 404 NOT FOUND (retired / unavailable)
# - gemini-3.5-flash-lite  → 503 Timeout (frequently overloaded, causes 20-min hangs)
# - gemini-2.5-flash       → 404 NOT FOUND
LITE_TIER_MODELS = [
    "gemini-3.1-flash-lite",   # Primary: fast, reliable, free-tier friendly
    "gemini-3-flash-preview",  # Fallback: slightly slower but stable
]

SMART_TIER_MODELS = [
    "gemini-3.1-flash-lite",   # Primary: sufficient for structured output tasks
    "gemini-3-flash-preview",  # Fallback
]

# Backward-compatible aliases
FAST_LITE_MODELS = LITE_TIER_MODELS
SMART_FLASH_MODELS = SMART_TIER_MODELS

# Minimum seconds between calls per tier to respect RPM quotas
TIER_PACING: Dict[str, float] = {
    "lite": 1.2,    # 15 RPM capacity
    "smart": 3.5,   # 5 RPM capacity
}

_pacing_lock = threading.Lock()
_last_call_time: Dict[str, float] = {
    "lite": 0.0,
    "smart": 0.0,
}


def get_key_pool() -> List[str]:
    """
    Parses GEMINI_API_KEYS from environment (comma-separated).
    Falls back to GOOGLE_API_KEY if GEMINI_API_KEYS is missing.
    """
    raw = os.getenv("GEMINI_API_KEYS", "")
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        fallback = os.getenv("GOOGLE_API_KEY", "").strip()
        if fallback:
            keys = [fallback]
    return keys


class KeyPoolManager:
    """Thread-safe round-robin manager for API keys."""

    def __init__(self):
        self._lock = threading.Lock()
        self._index = 0

    def get_next_key(self) -> str:
        """Returns the next round-robin key from the pool."""
        keys = get_key_pool()
        if not keys:
            raise ValueError(
                "No Gemini API keys found. Set GEMINI_API_KEYS or GOOGLE_API_KEY in .env"
            )
        with self._lock:
            key = keys[self._index % len(keys)]
            self._index = (self._index + 1) % len(keys)
            return key

    def get_ordered_keys(self) -> List[str]:
        """
        Returns all active keys starting from the current round-robin position.
        Advances the round-robin pointer by 1 for the calling request.
        """
        keys = get_key_pool()
        if not keys:
            raise ValueError(
                "No Gemini API keys found. Set GEMINI_API_KEYS or GOOGLE_API_KEY in .env"
            )
        with self._lock:
            start_idx = self._index % len(keys)
            self._index = (self._index + 1) % len(keys)

        # Shift keys so start_idx is first, followed by others in order
        return [keys[(start_idx + i) % len(keys)] for i in range(len(keys))]


key_pool = KeyPoolManager()

# Track metadata of the most recent successful execution
_last_execution_meta: Dict[str, Any] = {
    "model": "",
    "key_suffix": "",
    "tier": "",
}
_meta_lock = threading.Lock()


def get_last_execution_meta() -> Dict[str, Any]:
    """Returns metadata regarding the model and key used in the last invocation."""
    with _meta_lock:
        return _last_execution_meta.copy()


def _is_quota_error(exc: Exception) -> bool:
    """Determines whether an exception is due to 429 or quota exhaustion."""
    err_str = str(exc).lower()
    code = getattr(exc, "status_code", None)
    if code == 429:
        return True
    quota_terms = ["429", "resourceexhausted", "quotaexceeded", "rate limit", "quota reached"]
    return any(term in err_str for term in quota_terms)


def _is_not_found_error(exc: Exception) -> bool:
    """Determines whether an exception is due to 404 (model not found / retired)."""
    err_str = str(exc).lower()
    code = getattr(exc, "status_code", None)
    if code == 404:
        return True
    return "404" in err_str or "not_found" in err_str


def _is_server_unavailable_error(exc: Exception) -> bool:
    """
    Determines whether an exception is due to 503, high demand, server overload,
    or network timeout.
    """
    err_str = str(exc).lower()
    code = getattr(exc, "status_code", None)
    if code in (503, 500, 502, 504):
        return True
    unavailable_terms = [
        "503", "unavailable", "servererror", "overloaded",
        "high demand", "timeout", "timed out", "service unavailable", "deadline exceeded"
    ]
    return any(term in err_str for term in unavailable_terms)


def _enforce_pacing(tier: str) -> None:
    """Enforces rate-limit pacing delay before issuing an LLM call."""
    min_spacing = TIER_PACING.get(tier, 1.2)
    with _pacing_lock:
        elapsed = time.time() - _last_call_time.get(tier, 0.0)
        if elapsed < min_spacing:
            wait_time = min_spacing - elapsed
            logger.debug(f"Pacing: waiting {wait_time:.2f}s for {tier} tier")
            time.sleep(wait_time)
        _last_call_time[tier] = time.time()


def invoke_structured_llm(
    schema_cls: Type[T],
    prompt_text: str,
    tier: str = "lite",
    return_meta: bool = False,
) -> Union[T, Tuple[T, Dict[str, Any]]]:
    """
    Invokes Gemini with structured output, supporting:
      1. Round-robin multi-key pool rotation.
      2. Immediate key failover on 429/ResourceExhausted.
      3. Immediate model failover on 503/UNAVAILABLE/Timeout (max_retries=1, timeout=20).
      4. Fallback model chain if all keys are exhausted for a model.

    Args:
        schema_cls: Pydantic model class for structured output.
        prompt_text: The prompt text to evaluate.
        tier: "lite" or "smart".
        return_meta: If True, returns tuple of (result, meta_dict).

    Returns:
        Parsed instance of schema_cls (or (result, meta) if return_meta=True).
    """
    models = LITE_TIER_MODELS if tier == "lite" else SMART_TIER_MODELS
    keys_to_try = key_pool.get_ordered_keys()
    last_error: Optional[Exception] = None

    for model_name in models:
        logger.info(f"[LLM Router] Evaluating model: {model_name} (tier={tier})")
        all_keys_quota_exhausted = True

        for key in keys_to_try:
            key_suffix = f"...{key[-4:]}"
            _enforce_pacing(tier)

            try:
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    google_api_key=key,
                    temperature=0.1,
                    max_retries=1,
                    timeout=20,
                )
                structured_llm = llm.with_structured_output(schema_cls)
                result = structured_llm.invoke(prompt_text)

                meta = {
                    "model": model_name,
                    "key_suffix": key_suffix,
                    "tier": tier,
                }
                with _meta_lock:
                    _last_execution_meta.update(meta)

                logger.info(f"[LLM Router] Success with {model_name} using key {key_suffix}")
                if return_meta:
                    return result, meta
                return result

            except Exception as e:
                last_error = e

                # 1. 503 Service Unavailable / Timeout / Overload -> Immediately switch model!
                if _is_server_unavailable_error(e):
                    logger.warning(
                        f"[LLM Router] Model {model_name} returned 503/Unavailable/Timeout: {str(e)[:120]}. "
                        f"Immediately switching to next model in tier..."
                    )
                    all_keys_quota_exhausted = False
                    break

                # 2. 429 Quota Exhausted on this key -> Try next key in pool
                if _is_quota_error(e):
                    logger.warning(
                        f"[LLM Router] Key ending in {key_suffix} hit quota for {model_name}. "
                        f"Rotating to next key in pool..."
                    )
                    continue

                # 3. 404 Model Not Found -> Switch model
                if _is_not_found_error(e):
                    logger.warning(
                        f"[LLM Router] Model {model_name} returned 404/NotFound. Downgrading to next model..."
                    )
                    all_keys_quota_exhausted = False
                    break

                # 4. Other unexpected errors -> Try next model
                logger.error(f"[LLM Router] Error with {model_name} using key {key_suffix}: {e}")
                all_keys_quota_exhausted = False
                break

        if all_keys_quota_exhausted:
            logger.warning(
                f"[LLM Router] All keys exhausted for model {model_name}. Downgrading to next model in chain."
            )

    raise RuntimeError(
        f"All models in '{tier}' tier and all API keys exhausted. Last error: {last_error}"
    )
