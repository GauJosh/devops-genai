# DevOps GenAI Platform – AI Infrastructure Lab

## Vision

This repository is a **production-style AI Platform Engineering Lab** designed to demonstrate:

- Inference architecture design
- Model abstraction & routing
- Kubernetes-native AI workloads
- Observability-first LLM systems
- Cost & capacity modeling
- Multi-tenant AI gateway patterns
- Enterprise translation patterns

The goal is not to build a chatbot.

The goal is to design, deploy, and reason about **LLM infrastructure as a platform engineer.**

---

# Architecture Philosophy

The platform is designed in layers:

Client  
↓  
API Layer / RAG Service  
↓  
Inference Router  
↓  
Model Adapters (OpenAI / Mock / Local / Azure)  
↓  
Model Serving Layer (API / Ollama / vLLM)  
↓  
Compute (CPU / GPU)

Each layer is isolated and replaceable.

---

# Phase 1 – Core RAG Engine (Framework-Agnostic)

**Goal:** Understand RAG deeply without framework abstraction.

## RAG Internals

- [x] Document ingestion endpoint  
- [x] Log-aware & doc-aware chunking strategy  
- [x] Embedding generation  
- [x] Chroma vector storage  
- [x] Retrieval logic (top-k + scoring)  
- [x] Context injection strategy  
- [x] Prompt templating  
- [ ] Prompt versioning  
- [x] Response citations  
- [x] Evaluation harness (golden prompts)  

## Cost & Usage Awareness

- [x] Token logging  
- [x] Cost estimation per request  
- [ ] Usage reporting endpoint  
- [ ] Prompt version tracking  

## Data Layer Evolution

- [ ] PostgreSQL + pgvector migration  
- [ ] Redis caching layer  
- [ ] Embedding model comparison  
- [ ] Dataset versioning strategy  

---

# Phase 2 – Kubernetes Platformization

**Goal:** Treat RAG like a production service.

## Containerization

- [x] Dockerfile  
- [ ] Multi-stage optimization  
- [x] Environment-based configuration  
- [x] Secret management pattern  

## Kubernetes Deployment

- [x] Deployment  
- [x] Service  
- [x] ConfigMaps  
- [x] Secrets  
- [x] HPA (CPU-based)  
- [x] Liveness probe  
- [x] Readiness probe  
- [x] Resource limits & requests  
- [ ] Load testing & throughput benchmarks  
- [ ] Pod disruption budget  

## Infrastructure as Code

- [ ] Helm chart  
- [ ] Terraform cloud translation skeleton  

---

# Phase 2.5 – Inference Architecture & Model Serving

**Goal:** Move beyond API usage into LLM infrastructure design.

## Inference Router Layer (Critical)

- [x] Dedicated inference-router service  
- [x] Multi-model routing strategy  
- [x] Fallback logic  
- [ ] Timeout & retry policies  
- [ ] Model selection heuristics  
- [ ] Traffic shadowing experiments  
- [x] Request-driven routing via `model_hint`  
- [x] Provider abstraction (OpenAI + Mock)  
- [x] Request ID propagation across services  
- [x] Structured failure handling  

## Local / Alternate Model Serving

- [ ] Run Ollama locally  
- [ ] Benchmark latency vs OpenAI API  
- [ ] Add real local-model adapter (Ollama)  
- [ ] Run vLLM locally  
- [ ] Compare CPU vs GPU inference behavior  
- [ ] Concurrency stress testing  

## Kubernetes Model Serving

- [ ] Deploy Ollama/vLLM to Minikube  
- [ ] Cold start measurement  
- [ ] Horizontal scaling of inference pods  
- [ ] Latency under load testing  

## Model Lifecycle Management

- [ ] Model versioning strategy  
- [ ] Canary rollout simulation  
- [ ] Rollback mechanism  
- [ ] Model performance comparison framework  

---

# Phase 3 – Observability & Capacity Engineering

**Goal:** Operate AI like real infrastructure.

- [x] Structured JSON logs  
- [x] p95 latency tracking  
- [ ] p99 latency tracking  
- [x] Token throughput metrics  
- [x] Prometheus integration  
- [ ] OpenTelemetry tracing  
- [x] Correlation IDs / request IDs  
- [ ] Retrieval quality logging  
- [ ] Prompt regression detection  
- [x] Cost dashboard (derived from token metrics + request accounting)  
- [ ] GPU utilization metrics (simulated if needed)  
- [ ] Capacity planning documentation  
- [ ] Throughput math modeling  
- [x] Grafana dashboard for traffic / latency / tokens / cost / reliability  

---

# Phase 4 – DevOps AI Applications

**Goal:** Apply platform capabilities to real DevOps workflows.

- [ ] Runbook RAG  
- [ ] Log analyzer endpoint  
- [ ] CI failure summarizer  
- [ ] Incident analysis endpoint  
- [ ] Postmortem draft generator  
- [ ] GitHub webhook integration  

---

# Phase 5 – Agent & Tooling Architecture

**Goal:** Structured multi-step automation (not hobby agents).

## Tool-Calling Architecture

- [ ] Tool abstraction layer  
- [ ] Deterministic execution wrapper  
- [ ] Tool permission boundaries  
- [ ] Tool-call audit logging  
- [ ] Guardrails evaluation  

## Multi-Agent Workflows

- [ ] Incident triage agent  
- [ ] Logs analysis agent  
- [ ] Remediation recommendation agent  
- [ ] Reporter agent  
- [ ] Confidence scoring  
- [ ] Human-in-the-loop approval flow  

---

# Phase 6 – AI Gateway & Multi-Tenancy

**Goal:** Production-grade enterprise patterns.

- [ ] JWT authentication  
- [ ] Role-based access  
- [ ] Tenant isolation model  
- [ ] Rate limiting per tenant  
- [ ] Per-tenant quotas  
- [ ] Prompt injection mitigation  
- [ ] Secret redaction checks  
- [ ] Tool-call allowlist enforcement  
- [ ] Cost allocation per tenant  

---

# Phase 7 – Enterprise Translation

**Goal:** Map local architecture to enterprise cloud patterns.

- [ ] Azure OpenAI adapter  
- [ ] AKS deployment  
- [ ] Azure Monitor integration  
- [ ] AAD authentication  
- [ ] Enterprise cost tracking  
- [ ] Governance documentation  
- [ ] Multi-region inference considerations  

---

# Advanced Topics (Staff-Level Depth)

- [ ] Continuous batching (vLLM theory)  
- [ ] KV cache memory tradeoffs  
- [ ] GPU scheduling models  
- [ ] Model sharding concepts  
- [ ] Multi-tenant GPU sharing strategies  
- [ ] AI SLO definition  
- [ ] Failure isolation design  

---

# Repository Structure Target

- `services/rag-service/` – public API, retrieval, prompt assembly, embedding path  
- `services/inference-router/` – routing, provider adapters, fallback, inference metrics  
- `deploy/` – Kubernetes manifests and future Helm  
- `eval/` – evaluation harness  
- `docs/` – architecture and routing docs  
- `infra/` – future Terraform / cloud translation  

---

# Current Milestone Summary

Completed platform milestones:

- RAG service deployed on Kubernetes
- Dedicated inference-router service
- OpenAI provider integration
- Mock fallback provider integration
- Request-driven model routing via `model_hint`
- Structured logs across services
- Cross-service request tracing
- Prometheus metrics on inference-router
- Grafana dashboard for traffic, latency, reliability, tokens, and cost
- Fallback behavior tested with controlled primary-model failure

---

# Near-Term Next Steps

1. Add Ollama as a real second provider  
2. Compare OpenAI vs local-model latency/cost behavior  
3. Add timeout + retry policy in router  
4. Add load testing and throughput analysis  
5. Document routing policy and architecture screenshots in README  

---

# Long-Term Outcome

This project demonstrates:

- Deep RAG internals understanding  
- Inference system architecture design  
- Multi-model routing capability  
- Fallback and graceful degradation patterns  
- LLM serving infrastructure knowledge  
- Kubernetes-native AI deployment  
- Observability-first AI engineering  
- Cost governance & capacity modeling  
- Enterprise AI platform readiness  

This is not a GenAI demo.

This is an AI infrastructure engineering lab.
