# CI/CD Failure Analysis Agent

## Overview
This document describes the DevOps AI agent built on top of the RAG + inference routing platform.

The system analyzes CI/CD pipeline failures by ingesting logs, retrieving relevant context, and generating structured troubleshooting responses.

---

## Key Capabilities
- Ingest CI/CD logs with metadata (repo, pipeline, environment)
- Retrieve relevant log/context using vector search
- Analyze failures using DevOps-specific prompt mode
- Provide root cause, evidence, and actionable fixes
- Multi-model routing (OpenAI, Ollama, Mock)
- Fallback and retry policies for reliability
- Observability via Prometheus + Grafana

---

## Architecture
Client → API → RAG Service → Inference Router → Provider (OpenAI / Ollama / Mock)

Vector Store:
- Chroma DB (running with PVC in Kubernetes)

---

## CI/CD Flow
1. Logs ingested via `/ingest-log`
2. Logs chunked and stored with metadata
3. `/ask` retrieves relevant chunks
4. DevOps prompt generates structured response

---

## Example Use Cases
- Kubernetes CrashLoopBackOff debugging
- Terraform authentication failures
- Container registry push failures

---

## Tradeoffs
- OpenAI: high quality, higher cost
- Mock: fast fallback, low quality
- Ollama: local, slower (CPU-bound)

---

## Prompt Design (CI/CD Mode)
Response format:
- Immediate Failure
- Likely Underlying Cause
- Evidence
- First 3 Checks
- Suggested Fix
- Confidence

Optimized for:
- concise output
- operational clarity
- minimal repetition

---

## Observability
- Prometheus metrics (latency, tokens, cost)
- Grafana dashboards:
  - success vs failure
  - latency
  - token usage
  - cost tracking

---

## Current Limitations
- Single-chunk retrieval in some scenarios
- No classification layer (yet)
- Limited runbook ingestion
- Ollama latency on CPU

---

## Next Steps (Work Translation)
- Replace OpenAI with Azure OpenAI
- Use enterprise vector DB (Postgres + pgvector or approved alternative)
- Integrate with CI/CD systems (GitHub Actions / Azure DevOps)
- Add authentication + RBAC
- Expand runbook ingestion
