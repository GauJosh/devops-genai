import os
import random
import time
import requests
from typing import List, Dict, Any, Optional

INFERENCE_ROUTER_URL = os.getenv("INFERENCE_ROUTER_URL", "http://inference-router:8000")
INFERENCE_TIMEOUT_S = float(os.getenv("INFERENCE_TIMEOUT_S", "150"))
INFERENCE_MAX_RETRIES = int(os.getenv("INFERENCE_MAX_RETRIES", "3"))
INFERENCE_BACKOFF_BASE_S = float(os.getenv("INFERENCE_BACKOFF_BASE_S", "1.0"))
INFERENCE_BACKOFF_MAX_S = float(os.getenv("INFERENCE_BACKOFF_MAX_S", "8.0"))

RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def generate_via_router(
    messages: List[Dict[str, str]],
    model_hint: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 800,
    request_id: Optional[str] = None,
    purpose: str = "rag",
) -> Dict[str, Any]:
    payload = {
        "request_id": request_id,
        "purpose": purpose,
        "messages": messages,
        "model_hint": model_hint,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout_ms": int(INFERENCE_TIMEOUT_S * 1000),
    }

    last_error: Optional[Exception] = None

    for attempt in range(1, INFERENCE_MAX_RETRIES + 1):
        try:
            r = requests.post(
                f"{INFERENCE_ROUTER_URL}/v1/generate",
                json=payload,
                timeout=INFERENCE_TIMEOUT_S,
            )

            if r.status_code in RETRYABLE_STATUS_CODES and attempt < INFERENCE_MAX_RETRIES:
                sleep_s = min(INFERENCE_BACKOFF_BASE_S * (2 ** (attempt - 1)), INFERENCE_BACKOFF_MAX_S)
                sleep_s += random.uniform(0, 0.25)
                time.sleep(sleep_s)
                continue

            r.raise_for_status()
            return r.json()
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            if attempt >= INFERENCE_MAX_RETRIES:
                raise
            sleep_s = min(INFERENCE_BACKOFF_BASE_S * (2 ** (attempt - 1)), INFERENCE_BACKOFF_MAX_S)
            sleep_s += random.uniform(0, 0.25)
            time.sleep(sleep_s)
        except requests.HTTPError as exc:
            last_error = exc
            response = exc.response
            if response is None or response.status_code not in RETRYABLE_STATUS_CODES or attempt >= INFERENCE_MAX_RETRIES:
                raise
            sleep_s = min(INFERENCE_BACKOFF_BASE_S * (2 ** (attempt - 1)), INFERENCE_BACKOFF_MAX_S)
            sleep_s += random.uniform(0, 0.25)
            time.sleep(sleep_s)

    if last_error is not None:
        raise last_error

    raise RuntimeError("Inference router request failed without a captured exception")