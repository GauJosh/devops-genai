# DevOps GenAI Platform

Production-style AI platform lab for DevOps workflows with split inference architecture, RAG retrieval, model routing/fallback, and Kubernetes-native deployment patterns.

## Architecture Diagram

![DevOps GenAI Architecture](docs/architecture_diagram.png)

## What’s in this workspace

- `rag-service`: public API for ingest/retrieve/ask/chat and in-memory cost aggregation.
- `inference-router`: internal generation gateway with provider abstraction (`openai`, `mock`), fallback logic, JSON logs, and Prometheus metrics.
- `deploy/k8s`: namespace, config, secret, deployments, services, PVC, and HPAs.
- `dashboard`: Grafana dashboards (`v1`, `v2`) for request, latency, token, and failure visibility.
- `eval`: golden prompt harness for regression checks (`eval/run_eval.py`, `eval/golden.json`).
- `docs`: architecture and routing design notes.
- `app.py`: legacy monolith prototype kept for reference.

## Repository Structure

```text
devops-genai/
├── README.md
├── app.py
├── requests.http
├── ROADMAP.md
├── dashboard/
│   ├── grafana-dashboard-v1.json
│   └── grafana-dashboard-v2.json
├── deploy/k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── pvc.yaml
│   ├── rag-deployment.yaml
│   ├── rag-service.yaml
│   ├── router-deployment.yaml
│   ├── router-service.yaml
│   └── hpa.yaml
├── docs/
│   ├── architecture_diagram.png
│   ├── inference-architecture.md
│   └── multi-model-routing.md
├── eval/
│   ├── golden.json
│   └── run_eval.py
└── services/
    ├── inference-router/
    │   ├── Dockerfile
    │   ├── requirements.txt
    │   └── app/
    └── rag-service/
        ├── Dockerfile
        ├── requirements.txt
        └── app/
```

## Core Flows

### 1) Ingestion (`rag-service`)
1. Accepts raw docs/logs via `/ingest`.
2. Applies content-aware chunking (`docs` vs `logs`).
3. Generates embeddings (`text-embedding-3-small`).
4. Stores chunks + metadata in ChromaDB.

### 2) Retrieval + Answer (`/ask`)
1. Embeds the question.
2. Retrieves top-k chunks from ChromaDB with optional metadata filters.
3. Builds citation-aware prompt template.
4. Calls `inference-router` (`/v1/generate`).
5. Returns answer, retrieved chunks, token usage, and endpoint cost fields.

### 3) Inference Routing (`inference-router`)
- `model_hint` starts with `gpt*` → `openai` adapter.
- `model_hint` starts with `mock*` → `mock` adapter.
- Otherwise → `ROUTER_DEFAULT_PROVIDER`.
- On primary failure, router optionally retries with `ROUTER_FALLBACK_PROVIDER` when enabled.

## API Endpoints

### `rag-service` (default `http://localhost:8000`)
- `GET /healthz`
- `POST /chat`
- `POST /ingest`
- `POST /ask`
- `GET /sources`
- `GET /ingested`
- `GET /costs`
- `DELETE /reset?confirm=true`
- `DELETE /delete_source?source=...`

### `inference-router` (default `http://localhost:8001`)
- `GET /healthz`
- `GET /metrics`
- `POST /v1/generate`

## Local Development

### 1) Python environment

```bash
python -m venv .venv
source .venv/Scripts/activate
```

### 2) Environment variables

Create `.env` in repo root:

```env
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_MODEL_DEFAULT=gpt-4o-mini
OPENAI_EMBED_MODEL=text-embedding-3-small
CHROMA_DIR=./chroma_db

ROUTER_DEFAULT_PROVIDER=openai
ROUTER_ENABLE_FALLBACK=true
ROUTER_FALLBACK_PROVIDER=mock

INFERENCE_ROUTER_URL=http://localhost:8001
INFERENCE_TIMEOUT_S=30
```

### 3) Install dependencies

```bash
pip install -r services/inference-router/requirements.txt
pip install -r services/rag-service/requirements.txt
```

### 4) Run services (two terminals)

Terminal A (`inference-router`):

```bash
cd services/inference-router
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

Terminal B (`rag-service`):

```bash
cd services/rag-service
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Use the `requests.http` file for quick endpoint testing.

## Docker

Build images:

```bash
docker build -t rag-service:local services/rag-service
docker build -t inference-router:local services/inference-router
```

Run example:

```bash
docker run --rm -p 8001:8000 --env-file .env inference-router:local
docker run --rm -p 8000:8000 --env-file .env -e INFERENCE_ROUTER_URL=http://host.docker.internal:8001 rag-service:local
```

## Kubernetes (Manifests in `deploy/k8s`)

Apply resources:

```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/pvc.yaml
kubectl apply -f deploy/k8s/router-deployment.yaml
kubectl apply -f deploy/k8s/router-service.yaml
kubectl apply -f deploy/k8s/rag-deployment.yaml
kubectl apply -f deploy/k8s/rag-service.yaml
kubectl apply -f deploy/k8s/hpa.yaml
```

Notes:
- Namespace: `devops-genai`
- `rag-service` mounts PVC `chroma-pvc` at `/data/chroma_db`
- HPA configured for both deployments (`min=1`, `max=3`, CPU target `60%`)
- `secret.yaml` must be updated with a valid `OPENAI_API_KEY`

## Observability

### Router metrics (`/metrics`)
- `inference_requests_total{provider,purpose,model}`
- `inference_failures_total{provider,purpose,failure_stage}`
- `inference_latency_seconds{provider,purpose,model}`
- `inference_input_tokens_total{provider,purpose,model}`
- `inference_output_tokens_total{provider,purpose,model}`

### Dashboards
- `dashboard/grafana-dashboard-v1.json`
- `dashboard/grafana-dashboard-v2.json`

## Evaluation Harness

Golden tests call `POST /ask` and validate answer shape/content and citations.

```bash
python eval/run_eval.py
```

Optional custom file:

```bash
python eval/run_eval.py eval/golden.json
```

## Useful Docs

- `docs/inference-architecture.md`
- `docs/multi-model-routing.md`
- `ROADMAP.md`

## Troubleshooting

- `OPENAI_API_KEY not set`: provide key in `.env` (local) or `deploy/k8s/secret.yaml` (K8s).
- `/ask` returns “Insufficient context”: ingest relevant docs/logs first via `/ingest`.
- Router 502 errors: inspect router logs for primary/fallback failure events.
- No autoscaling in cluster: verify metrics-server is installed for HPA.
