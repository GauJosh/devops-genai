# Routing Policy and Provider Tradeoffs

## Purpose

This document describes the current request routing policy for the DevOps GenAI Platform and explains why different providers are used for different situations.

The system currently supports:

- OpenAI
- Mock
- Ollama

The routing layer lives in the `inference-router` service.

---

## Current Routing Policy

Routing is driven by `model_hint` in the request payload.

### Rules

- `gpt-*` → route to **OpenAI**
- `mock-*` → route to **Mock**
- `llama*`, `phi*`, `mistral*`, `qwen*`, `gemma*` → route to **Ollama**
- unknown / null → use router default provider

### Current default provider

- **Primary default provider:** OpenAI

### Current fallback provider

- **Fallback provider:** Mock

---

## Why Mock Is the Current Fallback

The fallback provider should preserve service availability quickly when the primary provider fails.

In the current Minikube CPU-based lab environment:

- Mock is fast
- Mock is deterministic
- Mock returns immediately
- Mock is useful for degraded but successful responses

By contrast, Ollama currently behaves like an experimental local-inference path, not a fast emergency fallback.

---

## Why Ollama Is Not the Current Fallback

Ollama is integrated and working, but it is not the best fallback for this environment right now.

### Observed issues in current setup

- high first-response latency on Minikube CPU
- lower answer quality than OpenAI for the tested prompt
- model load / warmup overhead
- higher operational cost in terms of runtime ownership

Because of that, Ollama is currently treated as:

- an explicit alternative provider
- a local inference experiment
- a platform comparison path

not as the first emergency fallback.

---

## Provider Tradeoff Summary

| Provider | Latency | Quality | API Cost | Best Use |
|---|---:|---|---:|---|
| OpenAI | ~3s | High | Paid | quality-sensitive answers |
| Mock | ~0.2s | Low | Near-zero | fast degraded fallback |
| Ollama | very high first-response latency in current Minikube CPU setup | Lower than OpenAI in tested case | 0 external API cost | local inference experiments |

---

## Current Request Paths

### 1. OpenAI path

Request:

```json
{
  "model_hint": "gpt-4o-mini"
}
```

Behavior:

- router selects OpenAI
- request completes on primary path
- metrics show `provider="openai"`

---

### 2. Mock path

Request:

```json
{
  "model_hint": "mock-fast"
}
```

Behavior:

- router selects Mock directly
- request completes with low latency
- metrics show `provider="mock"`

---

### 3. Failure → Mock fallback path

Request:

```json
{
  "model_hint": "bad-model-name"
}
```

Behavior:

- router tries OpenAI
- OpenAI fails with model-not-found
- router falls back to Mock
- request completes successfully with degraded response

---

### 4. Explicit Ollama path

Request:

```json
{
  "model_hint": "llama3.2:1b"
}
```

Behavior:

- router selects Ollama
- request goes to local model runtime
- response may be slow in current Minikube CPU environment
- metrics show `provider="ollama"`

---

## Design Principle

The current routing policy optimizes for:

1. **Correctness and quality** on the primary path
2. **Fast degraded availability** on fallback
3. **Real local-model experimentation** without forcing it into the fallback path

This is intentional.

A fallback path should protect user experience, not just avoid API cost.

---

## Future Routing Improvements

Planned next-step improvements include:

- retry policy for transient OpenAI failures
- timeout-aware routing
- provider-level latency thresholds
- quality-aware routing decisions
- cost-aware routing decisions
- tenant-aware routing

---

## Summary

The current policy reflects real platform tradeoffs:

- OpenAI is the strong default for quality
- Mock is the fast fallback for availability
- Ollama is the real local-model path for experimentation

This gives the platform three useful modes:

- primary inference
- degraded fallback inference
- local inference experimentation
