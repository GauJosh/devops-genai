"""
Inference Router Main Application Module

Initializes and configures the FastAPI application for the inference router service.
The router intelligently dispatches LLM requests to configured providers (OpenAI, Ollama, mock)
with fallback support, request tracking, and Prometheus metrics.
"""
from fastapi import FastAPI, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from .routes import router

app = FastAPI(title="inference-router", version="0.1.0")
app.include_router(router)


@app.get("/healthz")
def healthz():
    """
    Health check endpoint for service readiness probes.

    Returns:
        dict: Status indicator confirming the inference router is operational.
    """
    return {"ok": True}


@app.get("/metrics")
def metrics():
    """
    Prometheus metrics endpoint.

    Exposes Prometheus-formatted metrics for inference request counts, latencies, and token usage.

    Returns:
        Response: Prometheus metrics in text format.
    """
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)