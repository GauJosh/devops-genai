import os
import requests
from typing import List, Dict, Any, Optional

INFERENCE_ROUTER_URL = os.getenv("INFERENCE_ROUTER_URL", "http://inference-router:8000")
INFERENCE_TIMEOUT_S = float(os.getenv("INFERENCE_TIMEOUT_S", "150"))


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

    r = requests.post(
        f"{INFERENCE_ROUTER_URL}/v1/generate",
        json=payload,
        timeout=INFERENCE_TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()