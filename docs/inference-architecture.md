# Inference Architecture

## Purpose

This document describes the current inference architecture for the DevOps GenAI Platform and explains why the system was split into:

- `rag-service`
- `inference-router`

The goal of this split is to move from a monolithic RAG application toward a production-style AI platform architecture.

---

## Current System Overview

The platform currently consists of two services:

### 1. rag-service
Responsible for:

- document ingestion
- chunking
- embedding generation
- vector storage and retrieval
- prompt assembly
- public API endpoints such as `/ingest`, `/ask`, `/chat`

### 2. inference-router
Responsible for:

- generation requests
- model/provider abstraction
- routing inference calls to the configured backend
- acting as the internal inference control layer

---

## Current High-Level Architecture

```text
Client
  ↓
rag-service
  ├── /ingest
  ├── /ask
  └── /chat
  ↓
Inference Router
  ↓
OpenAI Adapter
  ↓
OpenAI API
```

## For Retriveval Flows:
```text
Client
  ↓
rag-service
  ↓
Embed question
  ↓
ChromaDB retrieval
  ↓
Prompt construction
  ↓
Inference Router
  ↓
OpenAI generation
  ↓
Response to client
```


---

## Why This Split Was Introduced

### Previous Design (Monolith)
```text
Client
↓
FastAPI App
↓
OpenAI Embeddings
↓
ChromaDB
↓
OpenAI Chat
```


### Problems

- tight coupling to OpenAI SDK
- no abstraction for models/providers
- no place for routing logic
- hard to add fallback or multi-model support
- difficult to add observability

---

## New Design Benefits

### 1. Provider Abstraction

Application code no longer depends directly on OpenAI.

### 2. Routing Layer

A central place to implement:

- model selection
- fallback policies
- traffic routing

### 3. Observability Boundary

The router becomes the place for:

- latency tracking
- request counting
- token tracking
- error tracking

### 4. Cleaner Separation of Concerns

| Component           | Responsibility               |
|--------------------|------------------------------|
| rag-service        | Retrieval + prompt building  |
| inference-router   | Generation + routing         |

---

## Responsibility Breakdown

### rag-service

- public API layer
- ingestion
- embeddings
- retrieval
- prompt assembly
- calls inference-router

### inference-router

- generation endpoint (`/v1/generate`)
- provider abstraction
- adapter execution
- response normalization

---

## Why Embeddings Remain in rag-service

This is an intentional staged refactor.

Moving embeddings and generation together would:

- increase refactor complexity
- introduce multiple failure points

### Current Design

- embeddings handled locally in rag-service
- generation handled by inference-router

### Future Option

Move embeddings into:

- inference-router
- or dedicated embedding service

---

## Request Flow: /ask

1. Client sends question to rag-service
2. rag-service generates embedding
3. rag-service retrieves context from ChromaDB
4. rag-service builds prompt
5. rag-service calls inference-router
6. inference-router calls OpenAI
7. response returned to rag-service
8. rag-service returns final response

---

## Request Flow: /ingest

1. Client sends text
2. rag-service chunks content
3. rag-service generates embeddings
4. rag-service stores in ChromaDB
5. response returned

---

## Internal Inference Contract

Endpoint:
```text
POST /v1/generate
```


### Request includes:

- messages
- model_hint
- temperature
- max_tokens
- request_id

### Response includes:

- provider
- model_used
- output_text
- usage
- latency

---

## Current Limitations

- single provider (OpenAI only)
- no fallback logic
- embeddings not abstracted
- no centralized cost tracking
- no request tracing (before Step 2)
- no metrics system yet
- no multi-tenant support

---

## Near-Term Improvements

1. Structured logging (router + rag-service)
2. Request ID propagation
3. Failure handling structure
4. Centralized inference accounting
5. Additional adapters (Ollama, vLLM)

---

## Future Architecture

```text
Client
↓
Application Layer
↓
Inference Router
├── OpenAI Adapter
├── Ollama Adapter
├── vLLM Adapter
└── Azure Adapter
↓
Model Backends
```

---

## Summary

The system has transitioned from:

- monolithic RAG application

to:

- retrieval service + inference control layer

This establishes the foundation for:

- multi-model routing
- observability
- AI platform patterns
- enterprise AI architecture
