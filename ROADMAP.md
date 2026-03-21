# DevOps GenAI Platform – AI Infrastructure Lab

## Vision

This repository is a **production-style AI Platform Engineering Lab** designed to demonstrate:

- Inference architecture design
- Model abstraction & routing
- Kubernetes-native AI workloads
- Observability-first LLM systems
- CI/CD failure diagnostics using RAG
- Enterprise translation patterns

The goal is not to build a chatbot.

The goal is to design, deploy, and reason about **LLM infrastructure as a platform engineer.**

---

# Architecture Philosophy

The platform is designed in layers:
```text
CI/CD Logs  
↓  
Ingest API  
↓  
Vector DB (embeddings + metadata)  
↓  
RAG Service (retrieval + context assembly)  
↓  
Inference Router (model selection / retry / fallback)  
↓  
LLM Providers (OpenAI / Mock / future local)  
↓  
Observability (Prometheus / Grafana)
```
Each layer is isolated and replaceable.

---

# Phase 1 – Core RAG Engine (Complete)

## RAG Internals

- [x] Log ingestion endpoint  
- [x] Metadata-aware ingestion (repo, pipeline, environment)  
- [x] Embedding generation  
- [x] Chroma vector storage (PVC-backed in Kubernetes)  
- [x] Retrieval logic (top-k + scoring)  
- [x] Context assembly  
- [x] Prompt templating (structured CI/CD analysis)  
- [x] Response generation with actionable output  

## Cost & Usage Awareness

- [x] Token logging  
- [x] Cost estimation per request  

## Data Layer Evolution

- [ ] PostgreSQL + pgvector migration  
- [ ] Redis caching layer  
- [ ] Embedding model comparison  
- [ ] Dataset versioning strategy  

---

# Phase 2 – Kubernetes Platformization (Complete)

## Containerization

- [x] Dockerized services  
- [x] Environment-based configuration  
- [x] Secret management pattern  

## Kubernetes Deployment

- [x] Deployment + Service  
- [x] ConfigMaps + Secrets  
- [x] HPA (basic CPU-based)  
- [x] Liveness & readiness probes  
- [x] Resource limits & requests  
- [x] Persistent storage for vector DB (PVC)  

---

# Phase 2.5 – Inference Architecture (Complete)

## Inference Router

- [x] Dedicated inference-router service  
- [x] Multi-model routing  
- [x] Fallback logic (primary → mock)  
- [x] Request-driven routing (`model_hint`)  
- [x] Provider abstraction (OpenAI + Mock)  
- [x] Structured failure handling  
- [x] Cross-service request tracing  

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

# Phase 3 – Observability (Complete)

- [x] Structured JSON logs  
- [x] Prometheus metrics  
- [x] Token + cost metrics  
- [x] Latency tracking (p95)  
- [x] Correlation IDs  
- [x] Grafana dashboards:
  - latency
  - traffic
  - token usage
  - cost
  - failure rate  

---

# Phase 4 – CI/CD Failure Analysis (Complete – Core Use Case)

## Implemented

- [x] CI/CD log ingestion workflow  
- [x] RAG-based failure analysis  
- [x] Structured prompt for root cause + next steps  
- [x] Support for:
  - Kubernetes failures (CrashLoopBackOff, image pull issues)
  - Terraform/provider errors
  - Registry/auth failures  

This is now the **primary demonstration layer of the platform.**

---

# Phase 5 – GitHub Actions Integration (Next)

**Goal:** Move from synthetic logs → real pipeline failures

## Planned

- [ ] Create intentionally failing GitHub Action workflow  
- [ ] Capture workflow logs using `gh` CLI  
- [ ] Local ingestion script → `/ingest-log`  
- [ ] Run `/ask` for automated diagnosis  
- [ ] Save analysis output for demo  

## Multi-Agent Workflows
- [ ] Incident triage agent  
- [ ] Logs analysis agent  
- [ ] Remediation recommendation agent  
- [ ] Reporter agent  
- [ ] Confidence scoring  
- [ ] Human-in-the-loop approval flow

---

# Phase 6.1 – Inference Expansion (Next)

- [ ] Add Ollama as real secondary provider  
- [ ] Compare OpenAI vs local model latency  
- [ ] Add timeout + retry policies  
- [ ] Basic routing heuristics  

# Phase 6.2 – AI Gateway & Multi-Tenancy

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
- [ ] Azure OpenAI adapter  
- [ ] AKS deployment  
- [ ] Azure Monitor integration  
- [ ] AAD authentication  
- [ ] Enterprise cost tracking  
- [ ] Governance documentation  
- [ ] Multi-region inference considerations 

---

# Phase 7 – Platform Hardening (Later)

- [ ] Load testing & throughput benchmarks  
- [ ] Helm chart  
- [ ] OpenTelemetry tracing  
- [ ] Retrieval quality metrics  
- [ ] Prompt versioning  
- [ ] Continuous batching (vLLM theory)  
- [ ] KV cache memory tradeoffs  
- [ ] GPU scheduling models  
- [ ] Model sharding concepts  
- [ ] Multi-tenant GPU sharing strategies  
- [ ] AI SLO definition  
- [ ] Failure isolation design  

---

# Phase 8 – Enterprise Translation (Later)

- [ ] Azure OpenAI adapter  
- [ ] AKS deployment model  
- [ ] Enterprise auth patterns  
- [ ] Secure vector store options  

---

# Repository Structure

- `services/rag-service/` – ingestion, retrieval, prompt assembly  
- `services/inference-router/` – routing, fallback, providers  
- `deploy/` – Kubernetes manifests  
- `docs/` – architecture diagrams  
- `eval/` – evaluation harness  

---

# Current Milestone Summary

## Completed platform milestones:

- RAG-based CI/CD failure analysis
- Kubernetes deployment with persistent vector DB
- Dedicated inference router with fallback
- Multi-provider abstraction (OpenAI + Mock)
- Prometheus + Grafana observability
- Structured prompts producing actionable outputs

---

# Near-Term Next Steps

1. GitHub Actions failure → ingestion → analysis loop  
2. Add real second provider (Ollama)  
3. Add retry + timeout policies  
4. Document architecture + demo flow in README  

---

# Long-Term Outcome

This project demonstrates:

- RAG applied to real DevOps workflows  
- Inference system architecture (not just API usage)  
- Multi-model routing and fallback  
- Kubernetes-native AI systems  
- Observability-first LLM engineering  
- Practical AI for platform engineering  

This is not a GenAI demo.

This is an **AI infrastructure engineering lab.**