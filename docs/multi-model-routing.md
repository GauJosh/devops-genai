# Multi-Model Routing, Fallback & Observability

This project implements a simple but realistic AI inference control plane with:

- Multi-model routing via `model_hint`
- Provider abstraction (OpenAI + Mock)
- Automatic fallback on failure
- Full observability (logs + Prometheus + Grafana)
- Cost and token tracking

---

## Architecture Overview

Client (/ask)
   ↓
RAG Service
   ↓ (calls)
Inference Router
   ↓
Primary Provider (OpenAI)
   ↓ (on failure)
Fallback Provider (Mock)

---

## Routing Behavior

Routing is controlled via request payload:

{
  "model_hint": "gpt-4o-mini"
}

Supported paths:
- gpt-4o-mini → OpenAI
- mock-fast → Mock provider
- bad-model-name → fallback to mock
- null → default model

---

## Example Requests

Primary:
curl -X POST http://localhost:18000/ask -H "Content-Type: application/json" -d '{"question":"What does HPA do?","model_hint":"gpt-4o-mini"}'

Mock:
curl -X POST http://localhost:18000/ask -H "Content-Type: application/json" -d '{"question":"What does HPA do?","model_hint":"mock-fast"}'

Fallback:
curl -X POST http://localhost:18000/ask -H "Content-Type: application/json" -d '{"question":"What does HPA do?","model_hint":"bad-model-name"}'

---

## Observability

Key metrics:
- inference_requests_total
- inference_latency_seconds
- inference_cost_usd_total

PromQL:
sum(inference_requests_total) by (provider)

---

## Summary

You now have:
- routing control
- fallback
- observability
- cost tracking

This is a strong AI platform foundation.
