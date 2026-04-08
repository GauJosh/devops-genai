"""
Inference Router Routes Module

Implements intelligent request routing for LLM inference across multiple providers (OpenAI, Ollama, mock).
Features include provider selection based on model hints, fallback logic, request tracking, and Prometheus metrics.

Key endpoints:
  - POST /v1/generate: Route inference requests to appropriate provider with fallback
  - GET /healthz: Service health check
  - GET /metrics: Prometheus metrics for monitoring
"""
import json
import logging
import time
import requests
from fastapi import APIRouter, HTTPException
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError
from .schemas import GenerateRequest, GenerateResponse, ErrorResponse
from .adapters.openai_adapter import OpenAIAdapter
from .adapters.mock_adapter import MockAdapter
from .adapters.ollama_adapter import OllamaAdapter
from .config import (
    ROUTER_DEFAULT_PROVIDER,
    ROUTER_ENABLE_FALLBACK,
    ROUTER_FALLBACK_PROVIDER,
    OLLAMA_DEFAULT_MODEL,
)
from .metrics import (
    INFERENCE_REQUESTS_TOTAL,
    INFERENCE_FAILURES_TOTAL,
    INFERENCE_LATENCY_SECONDS,
    INFERENCE_INPUT_TOKENS_TOTAL,
    INFERENCE_OUTPUT_TOKENS_TOTAL,
)

router = APIRouter()

logger = logging.getLogger("inference-router")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

MAX_PRIMARY_RETRIES = 1


def get_adapter(provider_name: str):
    """Factory function to instantiate the appropriate inference adapter.

    Args:
        provider_name: Provider identifier ('openai', 'ollama', 'mock')

    Returns:
        Adapter instance

    Raises:
        ValueError: If provider is not supported
    """
    if provider_name == "openai":
        return OpenAIAdapter()
    if provider_name == "mock":
        return MockAdapter()
    if provider_name == "ollama":
        return OllamaAdapter()
    raise ValueError(f"Unsupported provider: {provider_name}")


def choose_primary_provider(req: GenerateRequest) -> str:
    model_hint = (req.model_hint or "").lower()

    if model_hint.startswith("mock"):
        return "mock"

    if model_hint.startswith("gpt"):
        return "openai"

    ollama_prefixes = ("llama", "phi", "mistral", "qwen", "gemma")
    if model_hint.startswith(ollama_prefixes):
        return "ollama"

    if model_hint == OLLAMA_DEFAULT_MODEL.lower():
        return "ollama"

    return ROUTER_DEFAULT_PROVIDER


def maybe_choose_fallback_provider(primary_provider: str) -> str | None:
    if not ROUTER_ENABLE_FALLBACK:
        return None
    if not ROUTER_FALLBACK_PROVIDER:
        return None
    if ROUTER_FALLBACK_PROVIDER == primary_provider:
        return None
    return ROUTER_FALLBACK_PROVIDER


def should_retry(provider_name: str, error: Exception) -> bool:
    if provider_name != "openai":
        return False

    transient_openai_errors = (
        APITimeoutError,
        APIConnectionError,
        InternalServerError,
        RateLimitError,
    )

    if isinstance(error, transient_openai_errors):
        return True

    if isinstance(error, requests.exceptions.Timeout):
        return True

    if isinstance(error, requests.exceptions.ConnectionError):
        return True

    return False


def log_start(req: GenerateRequest):
    logger.info(json.dumps({
        "event": "inference_request_start",
        "request_id": req.request_id,
        "purpose": req.purpose,
        "model_hint": req.model_hint,
        "message_count": len(req.messages),
    }))


def log_success(req: GenerateRequest, resp: GenerateResponse, wall_time_ms: int):
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
        "wall_time_ms": wall_time_ms,
    }))


def log_primary_failure(req: GenerateRequest, provider_name: str, error: Exception, wall_time_ms: int):
    logger.error(json.dumps({
        "event": "inference_primary_failed",
        "request_id": req.request_id,
        "purpose": req.purpose,
        "provider_attempted": provider_name,
        "model_hint": req.model_hint,
        "error_type": type(error).__name__,
        "error": str(error),
        "wall_time_ms": wall_time_ms,
    }))


def log_retry(req: GenerateRequest, provider_name: str, attempt: int):
    logger.warning(json.dumps({
        "event": "inference_retry_attempt",
        "request_id": req.request_id,
        "purpose": req.purpose,
        "provider": provider_name,
        "retry_attempt": attempt,
    }))


def log_fallback_attempt(req: GenerateRequest, fallback_provider: str):
    logger.info(json.dumps({
        "event": "inference_fallback_attempt",
        "request_id": req.request_id,
        "purpose": req.purpose,
        "fallback_provider": fallback_provider,
    }))


def log_fallback_failure(req: GenerateRequest, fallback_provider: str, error: Exception, wall_time_ms: int):
    logger.error(json.dumps({
        "event": "inference_fallback_failed",
        "request_id": req.request_id,
        "purpose": req.purpose,
        "fallback_provider": fallback_provider,
        "error_type": type(error).__name__,
        "error": str(error),
        "wall_time_ms": wall_time_ms,
    }))


def execute_with_provider(req: GenerateRequest, provider_name: str) -> GenerateResponse:
    adapter = get_adapter(provider_name)
    return adapter.generate(req)


def execute_primary_with_retry(req: GenerateRequest, provider_name: str) -> GenerateResponse:
    attempt = 0
    while True:
        try:
            return execute_with_provider(req, provider_name)
        except Exception as e:
            if attempt >= MAX_PRIMARY_RETRIES or not should_retry(provider_name, e):
                raise
            attempt += 1
            log_retry(req, provider_name, attempt)
            time.sleep(1)


def record_success_metrics(req: GenerateRequest, resp: GenerateResponse):
    provider = resp.provider
    purpose = req.purpose or "unknown"
    model = resp.model_used or "unknown"

    INFERENCE_REQUESTS_TOTAL.labels(
        provider=provider,
        purpose=purpose,
        model=model,
    ).inc()

    INFERENCE_LATENCY_SECONDS.labels(
        provider=provider,
        purpose=purpose,
        model=model,
    ).observe(resp.latency_ms / 1000.0)

    INFERENCE_INPUT_TOKENS_TOTAL.labels(
        provider=provider,
        purpose=purpose,
        model=model,
    ).inc(resp.usage.input_tokens)

    INFERENCE_OUTPUT_TOKENS_TOTAL.labels(
        provider=provider,
        purpose=purpose,
        model=model,
    ).inc(resp.usage.output_tokens)


def record_failure_metrics(provider: str, purpose: str, failure_stage: str):
    INFERENCE_FAILURES_TOTAL.labels(
        provider=provider,
        purpose=purpose,
        failure_stage=failure_stage,
    ).inc()


@router.post(
    "/v1/generate",
    response_model=GenerateResponse,
    responses={502: {"model": ErrorResponse}},
)
def generate(req: GenerateRequest):
    t0 = time.time()
    log_start(req)

    primary_provider = choose_primary_provider(req)
    purpose = req.purpose or "unknown"

    try:
        resp = execute_primary_with_retry(req, primary_provider)
        record_success_metrics(req, resp)
        log_success(req, resp, int((time.time() - t0) * 1000))
        return resp
    except Exception as primary_error:
        primary_wall_time_ms = int((time.time() - t0) * 1000)
        record_failure_metrics(
            provider=primary_provider,
            purpose=purpose,
            failure_stage="primary_generation",
        )
        log_primary_failure(req, primary_provider, primary_error, primary_wall_time_ms)

        fallback_provider = maybe_choose_fallback_provider(primary_provider)
        if not fallback_provider:
            raise HTTPException(
                status_code=502,
                detail=ErrorResponse(
                    request_id=req.request_id,
                    error="inference_failed",
                    provider_attempted=primary_provider,
                    fallback_attempted=False,
                    fallback_provider=None,
                    failure_stage="primary_generation",
                    detail=str(primary_error),
                ).model_dump()
            )

        try:
            log_fallback_attempt(req, fallback_provider)
            resp = execute_with_provider(req, fallback_provider)
            record_success_metrics(req, resp)
            log_success(req, resp, int((time.time() - t0) * 1000))
            return resp
        except Exception as fallback_error:
            fallback_wall_time_ms = int((time.time() - t0) * 1000)
            record_failure_metrics(
                provider=fallback_provider,
                purpose=purpose,
                failure_stage="fallback_generation",
            )
            log_fallback_failure(req, fallback_provider, fallback_error, fallback_wall_time_ms)

            raise HTTPException(
                status_code=502,
                detail=ErrorResponse(
                    request_id=req.request_id,
                    error="inference_failed",
                    provider_attempted=primary_provider,
                    fallback_attempted=True,
                    fallback_provider=fallback_provider,
                    failure_stage="fallback_generation",
                    detail=str(fallback_error),
                ).model_dump()
            )