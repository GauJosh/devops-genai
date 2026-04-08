"""
RAG Service Main Application Module

Initializes and configures the FastAPI application for the RAG (Retrieval-Augmented Generation)
service. This service handles document ingestion, semantic search, and LLM-powered question answering
using pgvector for vector storage and OpenAI for embeddings and generation.
"""
from fastapi import FastAPI
from .routes import router

app = FastAPI(title="rag-service", version="0.1.0")
app.include_router(router)


@app.get("/healthz")
def healthz():
    """
    Health check endpoint for service readiness probes.

    Returns:
        dict: Status object with "ok" flag and configured models/backends.
    """
    return {"ok": True}