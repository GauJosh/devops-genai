import os
import uuid
from typing import List, Optional, Literal, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
import hashlib

import chromadb
import time
import threading
from collections import defaultdict


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

# ---- Pricing (USD per 1M tokens) ----
DEFAULT_PRICING_PER_1M = {
    # Chat model
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},  # per 1M tokens :contentReference[oaicite:2]{index=2}

    # Embedding model
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},  # per 1M tokens :contentReference[oaicite:3]{index=3}
}

def get_pricing(model: str) -> dict:
    # Allow overriding via env later if you want
    return DEFAULT_PRICING_PER_1M.get(model, {"input": 0.0, "output": 0.0})

def cost_usd(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    p = get_pricing(model)
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


# ---- In-memory cost tracking (simple + good for local dev) ----
_cost_lock = threading.Lock()
_cost_totals = {
    "started_at": time.time(),
    "total_usd": 0.0,
    "by_endpoint": defaultdict(float),
    "by_model": defaultdict(float),
    "by_kind": defaultdict(float),  # e.g., "chat", "embeddings"
}

def add_cost(endpoint: str, model: str, kind: str, amount_usd: float):
    if amount_usd <= 0:
        return
    with _cost_lock:
        _cost_totals["total_usd"] += amount_usd
        _cost_totals["by_endpoint"][endpoint] += amount_usd
        _cost_totals["by_model"][model] += amount_usd
        _cost_totals["by_kind"][kind] += amount_usd

# Prompt versioning
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "You are a DevOps assistant.\n"
    "Use the provided context as the primary source of truth.\n"
    "Do not invent facts that are not supported by the context.\n"
    "If the context only shows symptoms (e.g., logs) and not the root cause, "
    "you MAY provide likely causes as 'Hypotheses' but label them clearly as hypotheses.\n"
    "Always include citations like [1], [2] when referencing context.\n"
    "End with 'Next data to ingest' describing what additional logs/runbook sections would help."
)

RAG_TEMPLATE = """PROMPT_VERSION={prompt_version}

CONTEXT (with citations):
{context}

QUESTION:
{question}

RESPONSE FORMAT (use headings exactly):
Summary:
- 1-2 sentences.

Evidence from context:
- Bullet points, each with citation(s).

Hypotheses (if needed):
- Bullet points of likely causes. If not needed, write: "None".

Next data to ingest:
- Bullet points of what additional info/logs/runbook sections would help confirm the cause.

Rules:
- If you reference context, include citations.
- Do not claim certainty without evidence.
"""

app = FastAPI(title="DevOps GenAI Assistant")

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Persistent Chroma store (saved on disk)
CHROMA_DIR = os.getenv("CHROMA_DIR", "./chroma_db")
chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)

# One collection for now; later we can support multiple namespaces/tenants
collection = chroma_client.get_or_create_collection(name="devops_knowledge")


class IngestRequest(BaseModel):
    source: str = Field(default="manual", description="Where this text came from (runbook, logs, etc.)")
    content_type: Literal["logs", "docs"] = Field(default="docs", description="Chunking strategy hint")
    text: str = Field(..., description="Raw text to ingest")
    chunk_size: int = Field(default=1200, ge=200, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)

class IngestedItem(BaseModel):
    id: str
    doc_id: str
    source: str
    content_type: str
    chunk_index: int
    text: str

class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    min_relevance: float = Field(
        default=1.2,
        ge=0.0,
        description="Distance threshold for filtering weak matches"
    )
    content_type: Optional[Literal["logs", "docs"]] = None
    source: Optional[str] = None


class RetrievedChunk(BaseModel):
    citation: str
    source: str
    content_type: str
    chunk_index: int
    text: str
    distance: Optional[float] = None


class AskResponse(BaseModel):
    answer: str
    prompt_version: str
    retrieved: List[RetrievedChunk]
    usage: Optional[Dict[str, Any]] = None

    embed_tokens: int = 0
    embed_cost_usd: float = 0.0
    chat_prompt_tokens: int = 0
    chat_completion_tokens: int = 0
    chat_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


class ChatRequest(BaseModel):
    prompt: str


class SourceSummary(BaseModel):
    source: str
    content_type: str
    chunks: int


class IngestResponse(BaseModel):
    doc_id: str
    chunks_added: int
    embed_tokens: int
    embed_cost_usd: float


@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "embed_model": EMBED_MODEL,
        "prompt_version": PROMPT_VERSION,
        "chroma_dir": CHROMA_DIR,
    }


@app.post("/chat")
def chat(req: ChatRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in .env")

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful DevOps assistant."},
                {"role": "user", "content": req.prompt},
            ],
        )
        return {
            "answer": resp.choices[0].message.content,
            "usage": resp.usage.model_dump() if resp.usage else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def chunk_docs(text: str, chunk_size: int, overlap: int) -> List[str]:
    """
    Paragraph-aware chunker:
    - Split by blank lines into paragraphs
    - Pack paragraphs into chunks up to chunk_size
    - Add overlap by carrying last ~overlap chars from previous chunk
    """
    text = text.strip()
    if not text:
        return []

    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    cur: List[str] = []
    cur_len = 0

    for p in paras:
        p_len = len(p) + 2
        if cur and (cur_len + p_len > chunk_size):
            chunk = "\n\n".join(cur).strip()
            chunks.append(chunk)

            if overlap > 0 and chunk:
                tail = chunk[-overlap:]
                cur = [tail]
                cur_len = len(tail)
            else:
                cur = []
                cur_len = 0

        cur.append(p)
        cur_len += p_len

    if cur:
        chunks.append("\n\n".join(cur).strip())

    # Fallback: if everything was one giant paragraph
    if len(chunks) == 1 and len(chunks[0]) > chunk_size:
        return [
            text[i : i + chunk_size].strip()
            for i in range(0, len(text), max(1, chunk_size - overlap))
            if text[i : i + chunk_size].strip()
        ]

    return chunks


def chunk_logs(text: str, max_chars: int, overlap_lines: int = 5) -> List[str]:
    """
    Log-aware chunker: groups by lines to keep log events together.
    """
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    chunks = []
    cur: List[str] = []
    cur_len = 0

    for ln in lines:
        ln_len = len(ln) + 1
        if cur and (cur_len + ln_len > max_chars):
            chunks.append("\n".join(cur))
            # overlap last N lines
            cur = cur[-overlap_lines:] if overlap_lines > 0 else []
            cur_len = sum(len(x) + 1 for x in cur)

        cur.append(ln)
        cur_len += ln_len

    if cur:
        chunks.append("\n".join(cur))

    return chunks


def embed_texts(texts: List[str]) -> tuple[List[List[float]], int]:
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in .env")

    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    # embeddings are aligned with input order
    vectors = [item.embedding for item in resp.data]

    # Embeddings API includes usage in current SDKs; default to 0 if missing
    prompt_tokens = 0
    if getattr(resp, "usage", None) and getattr(resp.usage, "prompt_tokens", None) is not None:
        prompt_tokens = int(resp.usage.prompt_tokens)

    return vectors, prompt_tokens


@app.post("/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text is empty")

    doc_id = str(uuid.uuid4())

    if req.content_type == "logs":
        chunks = chunk_logs(req.text, max_chars=req.chunk_size, overlap_lines=5)
    else:
        chunks = chunk_docs(req.text, chunk_size=req.chunk_size, overlap=req.chunk_overlap)

    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks produced from input text")

    embeddings, embed_tokens = embed_texts(chunks)
    embed_cost = cost_usd(EMBED_MODEL, input_tokens=embed_tokens, output_tokens=0)
    add_cost(endpoint="/ingest", model=EMBED_MODEL, kind="embeddings", amount_usd=embed_cost)

    ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
    metadatas = [
        {"doc_id": doc_id, "source": req.source, "content_type": req.content_type, "chunk_index": i}
        for i in range(len(chunks))
    ]

    collection.add(
        ids=ids,
        documents=chunks,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return IngestResponse(
        doc_id=doc_id,
        chunks_added=len(chunks),
        embed_tokens=embed_tokens,
        embed_cost_usd=round(embed_cost, 10),
    )


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in .env")

    q_vecs, q_embed_tokens = embed_texts([req.question])
    q_embed = q_vecs[0]

    embed_cost = cost_usd(EMBED_MODEL, input_tokens=q_embed_tokens, output_tokens=0)
    add_cost(endpoint="/ask", model=EMBED_MODEL, kind="embeddings", amount_usd=embed_cost)

    # Optional filters for source/content_type
    where = {}
    if req.content_type:
        where["content_type"] = req.content_type
    if req.source:
        where["source"] = req.source

    query_kwargs = dict(
        query_embeddings=[q_embed],
        n_results=req.top_k,
        include=["documents", "metadatas", "distances"],
    )

    if where:
        query_kwargs["where"] = where

    results = collection.query(**query_kwargs)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]

    retrieved: List[RetrievedChunk] = []
    context_parts: List[str] = []
    seen = set()
    citation_num = 0

    for doc, meta, dist in zip(docs, metas, dists):

        # Filter weak matches
        if dist is not None and dist > req.min_relevance:
            continue

        source = meta.get("source", "unknown")
        content_type = meta.get("content_type", "docs")
        chunk_index = int(meta.get("chunk_index", -1))

        # Stable dedupe key (metadata + content hash)
        content_hash = hashlib.sha256(doc.encode("utf-8")).hexdigest()[:16]
        dedupe_key = (source, content_type, chunk_index, content_hash)

        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        citation_num += 1
        citation = f"[{citation_num}]"

        retrieved.append(
            RetrievedChunk(
                citation=citation,
                source=source,
                content_type=content_type,
                chunk_index=chunk_index,
                text=doc,
                distance=dist,
            )
        )

        context_parts.append(
            f"{citation} source={source} type={content_type} chunk={chunk_index}\n{doc}"
        )

    # If no relevant context remains after filtering
    if not retrieved:
        return AskResponse(
            answer="Insufficient context. Please ingest relevant data.",
            prompt_version=PROMPT_VERSION,
            retrieved=[],
            usage=None,
        )

    context = "\n\n".join(context_parts)

    user_prompt = RAG_TEMPLATE.format(
        prompt_version=PROMPT_VERSION,
        context=context,
        question=req.question,
    )

    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    # Chat cost from usage tokens
    chat_in = int(resp.usage.prompt_tokens) if resp.usage else 0
    chat_out = int(resp.usage.completion_tokens) if resp.usage else 0
    chat_cost = cost_usd(OPENAI_MODEL, input_tokens=chat_in, output_tokens=chat_out)
    add_cost(endpoint="/ask", model=OPENAI_MODEL, kind="chat", amount_usd=chat_cost)

    answer = resp.choices[0].message.content

    total = embed_cost + chat_cost

    return AskResponse(
        answer=answer,
        prompt_version=PROMPT_VERSION,
        retrieved=retrieved,
        usage=resp.usage.model_dump() if resp.usage else None,
        embed_tokens=q_embed_tokens,
        embed_cost_usd=round(embed_cost, 10),
        chat_prompt_tokens=chat_in,
        chat_completion_tokens=chat_out,
        chat_cost_usd=round(chat_cost, 10),
        total_cost_usd=round(total, 10),
    )

@app.get("/sources", response_model=List[SourceSummary])
def list_sources(limit: int = 5000):
    """
    Summary of what's ingested: counts by (source, content_type).
    limit is a safety cap (fine for local dev).
    """
    data = collection.get(include=["metadatas"], limit=limit)

    metadatas = data.get("metadatas", []) or []
    counts = {}

    for m in metadatas:
        src = m.get("source", "unknown")
        ctype = m.get("content_type", "unknown")
        key = (src, ctype)
        counts[key] = counts.get(key, 0) + 1

    # stable ordering for readability
    out = [
        SourceSummary(source=src, content_type=ctype, chunks=n)
        for (src, ctype), n in sorted(counts.items(), key=lambda x: (x[0][0], x[0][1]))
    ]
    return out

@app.get("/ingested", response_model=List[IngestedItem])
def list_ingested(
    limit: int = 200,
    source: Optional[str] = None,
    content_type: Optional[Literal["logs", "docs"]] = None,
    doc_id: Optional[str] = None,
):
    """
    Detailed view of ingested chunks (id + metadata + text).

    Notes:
    - Chroma get() supports metadata filtering via `where`.
    - limit is important so we don't dump huge amounts accidentally.
    """
    where = {}
    if source:
        where["source"] = source
    if content_type:
        where["content_type"] = content_type
    if doc_id:
        where["doc_id"] = doc_id

    kwargs = dict(include=["documents", "metadatas"])
    if where:
        kwargs["where"] = where

    data = collection.get(limit=limit, **kwargs)

    ids = data.get("ids", []) or []
    docs = data.get("documents", []) or []
    metas = data.get("metadatas", []) or []

    out: List[IngestedItem] = []
    for _id, doc, meta in zip(ids, docs, metas):
        out.append(
            IngestedItem(
                id=_id,
                doc_id=meta.get("doc_id", ""),
                source=meta.get("source", "unknown"),
                content_type=meta.get("content_type", "unknown"),
                chunk_index=int(meta.get("chunk_index", -1)),
                text=doc,
            )
        )

    # sort to make output deterministic and easier to scan
    out.sort(key=lambda x: (x.source, x.content_type, x.doc_id, x.chunk_index))
    return out

@app.get("/costs")
def costs():
    with _cost_lock:
        return {
            "started_at": _cost_totals["started_at"],
            "uptime_seconds": time.time() - _cost_totals["started_at"],
            "total_usd": round(_cost_totals["total_usd"], 8),
            "by_endpoint": {k: round(v, 8) for k, v in _cost_totals["by_endpoint"].items()},
            "by_model": {k: round(v, 8) for k, v in _cost_totals["by_model"].items()},
            "by_kind": {k: round(v, 8) for k, v in _cost_totals["by_kind"].items()},
        }

@app.delete("/reset")
def reset_collection(confirm: bool = False):
    """
    Deletes ALL stored chunks. For local dev only.
    """
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to reset")

    chroma_client.delete_collection("devops_knowledge")
    global collection
    collection = chroma_client.get_or_create_collection(name="devops_knowledge")
    return {"status": "ok", "message": "collection reset"}


@app.delete("/delete_source")
def delete_source(source: str):
    """
    Deletes all chunks that match a source label.
    """
    # Fetch ids matching the filter
    data = collection.get(where={"source": source}, include=["metadatas"])
    ids = data.get("ids", []) or []
    if not ids:
        return {"status": "ok", "deleted": 0, "source": source}

    collection.delete(ids=ids)
    return {"status": "ok", "deleted": len(ids), "source": source}