# Work-Ready Architecture — CI/CD Failure Analysis Agent

## Goal
Deploy an enterprise-ready AI assistant that analyzes CI/CD failures using internal logs and runbooks, operating within airgapped and security-constrained environments.

---

## Target Stack (Enterprise-Safe)

### Inference
- **Primary**: Azure OpenAI (chat + embeddings)
- **Fallback**: Mock provider (testing / resiliency)

### Vector Store
- **Preferred**: Postgres + pgvector
- **Alternatives**: Approved internal vector DB / managed service

### Platform
- Kubernetes (AKS or internal cluster)
- Existing CI/CD system (GitHub Actions / Azure DevOps)

---

## Architecture

```
CI/CD Pipeline
      ↓
/ingest-log (API)
      ↓
RAG Service (retrieval + prompt)
      ↓
Inference Router
      ↓
Azure OpenAI
      ↓
Response (Root cause + Fix)

Vector DB (pgvector)
      ↑
Embeddings (Azure OpenAI)
```
---

## Data Flow

### 1. Ingestion
- Pipeline step sends logs:
  - repo
  - pipeline
  - environment
  - status
  - raw logs

### 2. Storage
- Logs are:
  - chunked
  - embedded
  - stored with metadata

### 3. Query
- `/ask` endpoint:
  - filters by metadata
  - retrieves top-k chunks

### 4. Analysis
- CI/CD prompt mode generates:
  - Immediate Failure
  - Root Cause
  - Evidence
  - Checks
  - Fix

---

## Security Considerations

- No external outbound access (except Azure OpenAI)
- Secrets via:
  - environment variables
  - Azure Key Vault
- RBAC:
  - restrict access to endpoints
- No sensitive logs stored unencrypted

---

## CI/CD Integration Options

### Phase 1 (MVP)
- Add step in pipeline:
  - POST logs → `/ingest-log`

### Phase 2
- Automated ingestion:
  - webhook / event-based

### Phase 3
- Native integrations:
  - GitHub API
  - Azure DevOps API

---

## First Use Case (Recommended)

**AKS Deployment Failures**
- CrashLoopBackOff
- Image pull issues
- Config errors

OR

**Terraform Failures**
- Auth issues
- State issues
- Provider errors

Focus on ONE initially.

---

## Observability

- Prometheus:
  - request latency
  - token usage
  - cost
  - failure rate

- Grafana dashboards:
  - success vs failure
  - latency trends
  - cost tracking

---

## Known Tradeoffs

| Area | Tradeoff |
|------|--------|
| Azure OpenAI | High quality, cost considerations |
| pgvector | Operational overhead vs managed services |
| RAG | Requires good log/runbook coverage |
| Latency | Depends on model + retrieval |

---

## Future Enhancements

- Failure classification (build vs deploy vs infra)
- Runbook ingestion (internal docs)
- Multi-step agent workflows
- Auto-remediation suggestions
- Feedback loop (improve answers over time)

---

## Positioning

This system is:

- Not a chatbot
- A **DevOps AI assistant**
- Focused on:
  - reliability
  - troubleshooting
  - operational speed

---

## Summary

You now have:
- RAG-based CI/CD analysis
- Multi-provider inference routing
- Observability (metrics + dashboards)
- Kubernetes deployment

Next step:
👉 adapt to enterprise constraints and deploy internally
