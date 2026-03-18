import json
import logging
import time
from fastapi import APIRouter, HTTPException
from .schemas import GenerateRequest, GenerateResponse
from .adapters.openai_adapter import OpenAIAdapter

router = APIRouter()

logger = logging.getLogger("inference-router")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

_openai = OpenAIAdapter()


@router.post("/v1/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    t0 = time.time()

    logger.info(json.dumps({
        "event": "inference_request_start",
        "request_id": req.request_id,
        "purpose": req.purpose,
        "model_hint": req.model_hint,
        "message_count": len(req.messages),
    }))

    try:
        resp = _openai.generate(req)

        logger.info(json.dumps({
            "event": "inference_request_complete",
            "request_id": req.request_id,
            "purpose": req.purpose,
            "provider": resp.provider,
            "model_used": resp.model_used,
            "latency_ms": resp.latency_ms,
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "cost_usd": resp.usage.cost_usd,
            "wall_time_ms": int((time.time() - t0) * 1000),
        }))

        return resp
    except Exception as e:
        logger.error(json.dumps({
            "event": "inference_request_failed",
            "request_id": req.request_id,
            "purpose": req.purpose,
            "model_hint": req.model_hint,
            "error": str(e),
            "wall_time_ms": int((time.time() - t0) * 1000),
        }))
        raise HTTPException(status_code=502, detail=f"Inference failed: {e}")