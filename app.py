import os
import uuid
from typing import List, Optional, Literal, Dict, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
import hashlib

import chromadb


load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

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


class IngestResponse(BaseModel):
    doc_id: str
    chunks_added: int


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

class ChatRequest(BaseModel):
    prompt: str

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
    Basic doc chunker: sliding window by characters.
    Good enough to start; we can upgrade later.
    """
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(0, end - overlap)
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


def embed_texts(texts: List[str]) -> List[List[float]]:
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in .env")

    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    # Keep ordering aligned with input
    return [item.embedding for item in resp.data]


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

    embeddings = embed_texts(chunks)

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

    return IngestResponse(doc_id=doc_id, chunks_added=len(chunks))


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set in .env")

    q_embed = embed_texts([req.question])[0]

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

    answer = resp.choices[0].message.content

    return AskResponse(
        answer=answer,
        prompt_version=PROMPT_VERSION,
        retrieved=retrieved,
        usage=resp.usage.model_dump() if resp.usage else None,
    )