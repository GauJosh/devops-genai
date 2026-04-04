import os
import uuid
import time
import threading
import hashlib
import json
import logging
import tempfile
from collections import defaultdict
from typing import List, Optional, Literal, Dict, Any, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from openai import OpenAI
import chromadb

from .inference_client import generate_via_router

router = APIRouter()

logger = logging.getLogger("rag-service")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

# ---------------------------
# Config
# ---------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
CHROMA_DIR = os.getenv("CHROMA_DIR", "/data/chroma_db")

PROMPT_VERSION = "v3"

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

CICD_SYSTEM_PROMPT = (
    "You are a senior DevOps and platform engineer.\n"
    "Analyze CI/CD, deployment, Kubernetes, and infrastructure failures using the provided logs and retrieved context.\n"
    "Prioritize direct evidence from logs.\n"
    "Distinguish between the immediate failure and the likely underlying cause.\n"
    "Do not invent facts that are not supported by the context.\n"
    "Be decisive: select one primary diagnosis and one first fix when evidence supports it.\n"
    "Avoid weak hedging language (e.g., 'might', 'could', 'possibly') unless evidence is genuinely insufficient.\n"
    "If uncertain, state exactly what is uncertain and provide the most likely diagnosis anyway.\n"
    "Classify the failure into a concise category and subtype (e.g., Build Error / Image Pull, Runtime Error / File Not Found, Auth Error / Token Expired).\n"
    "Explicitly identify execution context: failing workflow/pipeline and failing job/step when evidence is present.\n"
    "Always include citations like [1], [2] when referencing context.\n"
    "Be concise, practical, and operational.\n"
    "Prefer concrete checks over generic advice.\n"
    "Keep responses short and operational. Avoid repeating the same point across sections.\n"
    "Prefer 1-2 bullets per section unless the logs clearly justify more.\n"
    "Do not ask the user to investigate many branches in parallel; prioritize the highest-probability path first.\n"
    "For CI/CD authentication issues, prefer non-interactive/service-principal or workload-identity style fixes unless the logs clearly show an interactive/manual environment.\n"
    "Make 'Fix First' actionable with explicit command(s), file edit(s), or config change(s); if exact values are unknown, provide a safe template with placeholders.\n"
    "When diagnosis involves missing files/paths/artifacts, include exact commands to verify existence and exact commands to add/commit/push or update path references.\n"
    "Do not present ephemeral CI runner paths (for example /home/runner/work/...) as commands for the user to run locally; convert them to repo-relative paths or clearly label them as CI-only evidence.\n"
    "Do not suggest creating empty placeholder files with commands like touch unless the context explicitly shows the file should be newly scaffolded and empty. Prefer restore, checkout, copy from the correct branch, or add the real expected file content.\n"
    "For Git commands that update files, suggest pushing to a feature branch or HEAD, never directly to main or master unless the context explicitly shows a main-only deployment model.\n"
)

CICD_RAG_TEMPLATE = """PROMPT_VERSION={prompt_version}

CONTEXT (with citations):
{context}

QUESTION:
{question}

RESPONSE FORMAT (use headings exactly):

Failure Category:
- Primary category and subtype in one bullet (e.g., "Build Error / Image Pull Failure").

Execution Context:
- 1-2 bullets naming workflow/pipeline and failing job/step if visible in context.
- If unavailable, say "Not clearly present in retrieved context".

Immediate Failure:
- 1-2 bullets describing what failed right now.

Primary Diagnosis:
- Exactly one bullet with the single most likely underlying cause.
- Start with: "Most likely root cause: ..."
- Include why the pipeline expected the resource/condition and what evidence shows it was missing or invalid.

Evidence:
- Bullet points with citation(s).

Fix First:
- 1-2 bullets with the first remediation to apply now.
- Include one concrete command or config change when possible.
- Prefer copy-pasteable commands or patch-style guidance.
- Include at least one "verify" command and one "remediate" command when possible.
- Use repo-relative paths for user commands unless explicitly marked as CI-only evidence.
- For missing files, prefer commands to verify, restore, checkout, or add the expected real file rather than creating an empty placeholder file.

Fallback if Fix Fails:
- 1-2 bullets for the next best action.

Top 3 Verifications:
- Three concrete checks in priority order to confirm resolution.
- Include command examples, not only descriptions.

Confidence:
- High / Medium / Low with one sentence.

Rules:
- If you reference context, include citations.
- Prefer log evidence over guesses.
- Separate symptom from root cause.
- Provide one primary diagnosis, not a list of equal-probability causes.
- Avoid generic recommendations when a more precise operational check is possible.
- Keep each section concise.
- Do not restate the same cause in multiple sections unless needed for clarity.
- Keep recommendations CI-platform-agnostic unless the log format clearly indicates a specific platform.
- Treat absolute CI workspace paths as evidence, not as local remediation commands.
- Never recommend creating or committing an empty placeholder file unless the context explicitly supports that action.
"""

FIX_SUGGESTION_SYSTEM_PROMPT = (
    "You are a DevOps engineer analyzing CI/CD failures. Provide fixes in EXACTLY this format:\n"
    "DIAGNOSIS: <one-sentence root cause>\n"
    "FIXES: [<JSON array of fixes or empty []>]\n"
    "\n"
    "CRITICAL: Each fix MUST be a JSON object with ALL these fields.\n"
    '- "fix_type": string\n'
    '- "auto_fix_possible": boolean\n'
    '- "target_file": string or null\n'
    '- "target_confidence": "High" | "Medium" | "Low"\n'
    '- "target_changes": array of objects: {"file": "path", "action": "add|modify|delete", "reason": "why this file"}\n'
    '- "suggested_change": string\n'
    '- "why_this_fix": string (brief reasoning tied to evidence)\n'
    '- "evidence_used": array of strings (specific observed facts from logs/context)\n'
    '- "assumptions": array of strings (can be empty)\n'
    '- "verification_steps": array of objects: {"step": "name", "command": "cmd", "expected_signal": "what confirms/denies"}\n'
    '- "alternatives_considered": array of strings\n'
    '- "patch_text": string or null (unified diff only when evidence supports exact change)\n'
    '- "workflow": array of objects: {"step": "name", "command": "cmd"}\n'
    '- "safe_to_auto_apply": boolean\n'
    '- "confidence": "High" | "Medium" | "Low"\n'
    '- "requires_review": boolean\n'
    "\n"
    "Rules:\n"
    "1. Always respond with EXACTLY two lines: one DIAGNOSIS line and one FIXES line\n"
    "2. Derive recommendations from evidence only\n"
    "3. Do not assume repository design, framework choice, or missing-file content\n"
    "4. Include verification steps before mutation steps in workflow\n"
    "5. target_file must be null when evidence is inconclusive\n"
    "6. patch_text must be null if exact change cannot be justified by evidence\n"
    "7. safe_to_auto_apply=true only for deterministic, low-risk, fully verifiable fixes\n"
    "8. NEVER assume branch names (don't hardcode main/master)\n"
    "9. NEVER hallucinate files or commands\n"
)

FIX_SUGGESTION_TEMPLATE = """PROMPT_VERSION={prompt_version}

Based on the failure logs and context, provide one diagnosis and 1-3 fix suggestions.

CONTEXT:
{context}

QUESTION:
{question}

For each fix suggestion, provide these fields in JSON:
- fix_type: evidence-derived category string
- auto_fix_possible: boolean
- target_file: file path needing fix (or null if no specific file)
- target_confidence: "High", "Medium", or "Low"
- target_changes: array of {{"file": "path", "action": "add|modify|delete", "reason": "why this file"}}
- suggested_change: brief human-readable description
- why_this_fix: concise reasoning tied to evidence
- evidence_used: array of concrete facts from logs/context
- assumptions: array of assumptions (empty if none)
- verification_steps: array of {{"step": "name", "command": "cmd", "expected_signal": "what confirms/denies"}}
- alternatives_considered: array of alternatives considered but not primary
- patch_text: unified diff if evidence supports exact change, otherwise null
- workflow: array of {{"step": "name", "command": "cmd"}}; start with verification steps before mutation
- safe_to_auto_apply: boolean (true only if safe deterministic auto-apply is justified)
- confidence: "High", "Medium", or "Low"
- requires_review: boolean

CRITICAL: Respond with EXACTLY two lines only (no other text):
DIAGNOSIS: <one-sentence root cause>
FIXES: [<JSON array or empty []>]

Example with evidence-first behavior:
DIAGNOSIS: CI references a test path that may be missing or mismatched with repository layout.
FIXES: [{{"fix_type": "path_or_workflow_mismatch", "auto_fix_possible": false, "target_file": null, "target_confidence": "Low", "target_changes": [{{"file": ".github/workflows/failing-ci.yml", "action": "modify", "reason": "Workflow may reference a non-existent test path"}}, {{"file": "tests/test_app.py", "action": "add", "reason": "May need restoration if file was deleted, but evidence is insufficient"}}], "suggested_change": "Verify whether the workflow test path is correct and whether the file exists before applying changes.", "why_this_fix": "Error mentions a missing test path, but logs do not conclusively prove whether file deletion or workflow misconfiguration is root cause. Target file is null because evidence is inconclusive.", "evidence_used": ["Observed error indicates missing tests/test_app.py path", "No direct evidence in logs that file should contain pytest scaffold"], "assumptions": ["Repository may have moved tests to a different folder", "File may have been deleted in a recent commit"], "verification_steps": [{{"step": "Check repository tree", "command": "git ls-tree -r --name-only HEAD | grep -E '^tests/'", "expected_signal": "Confirms whether tests/test_app.py exists"}}, {{"step": "Review workflow command", "command": "grep -n 'pytest\|test_app.py' .github/workflows/failing-ci.yml", "expected_signal": "Shows whether workflow points to the expected path"}}, {{"step": "Check file history", "command": "git log --oneline -- tests/test_app.py | head -5", "expected_signal": "Confirms whether file was deleted or never existed"}}], "alternatives_considered": ["Restore previously deleted test file based on git history", "Adjust workflow to run test discovery without hardcoded file path", "Create new test file if intended by design"], "patch_text": null, "workflow": [{{"step": "Create investigation branch", "command": "git checkout -b investigate-test-path-failure"}}, {{"step": "Run verification commands", "command": "git ls-tree -r --name-only HEAD | grep '^tests/' && grep -n 'pytest' .github/workflows/failing-ci.yml && git log -n 5 --oneline -- tests/test_app.py"}}, {{"step": "Review verification results and decide", "command": "If file exists: update workflow. If deleted: check git history. If never existed: verify design intent."}}, {{"step": "Open pull request with findings", "command": "gh pr create --title 'Fix CI after path/file verification'"}}], "safe_to_auto_apply": false, "confidence": "Medium", "requires_review": true}}]

Respond now (EXACTLY two lines, DIAGNOSIS and FIXES):\n"""

# ---------------------------
# Pricing + cost tracking
# ---------------------------
DEFAULT_PRICING_PER_1M = {
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}


def get_pricing(model: str) -> dict:
    return DEFAULT_PRICING_PER_1M.get(model, {"input": 0.0, "output": 0.0})


def cost_usd(model: str, input_tokens: int = 0, output_tokens: int = 0) -> float:
    p = get_pricing(model)
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


_cost_lock = threading.Lock()
_cost_totals = {
    "started_at": time.time(),
    "total_usd": 0.0,
    "by_endpoint": defaultdict(float),
    "by_model": defaultdict(float),
    "by_kind": defaultdict(float),  # "chat", "embeddings"
}


def add_cost(endpoint: str, model: str, kind: str, amount_usd: float):
    if amount_usd <= 0:
        return
    with _cost_lock:
        _cost_totals["total_usd"] += amount_usd
        _cost_totals["by_endpoint"][endpoint] += amount_usd
        _cost_totals["by_model"][model] += amount_usd
        _cost_totals["by_kind"][kind] += amount_usd


# ---------------------------
# Clients: OpenAI for embeddings, Chroma for storage
# ---------------------------
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

try:
    chroma_client = chromadb.PersistentClient(path=CHROMA_DIR)
except Exception as exc:
    default_fallback_chroma_dir = os.path.join(tempfile.gettempdir(), "chroma_db")
    fallback_chroma_dir = os.getenv("CHROMA_DIR_FALLBACK", default_fallback_chroma_dir)
    logger.warning(
        "Failed to initialize Chroma at CHROMA_DIR=%s (%s). Falling back to %s",
        CHROMA_DIR,
        exc,
        fallback_chroma_dir,
    )
    os.makedirs(fallback_chroma_dir, exist_ok=True)
    chroma_client = chromadb.PersistentClient(path=fallback_chroma_dir)

collection = chroma_client.get_or_create_collection(name="devops_knowledge")


# ---------------------------
# Schemas
# ---------------------------
class IngestRequest(BaseModel):
    source: str = Field(default="manual", description="Where this text came from (runbook, logs, etc.)")
    content_type: Literal["logs", "docs"] = Field(default="docs", description="Chunking strategy hint")
    text: str = Field(..., description="Raw text to ingest")
    chunk_size: int = Field(default=1200, ge=200, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)

    # Optional metadata for CI/CD and operational analysis
    repo: Optional[str] = None
    pipeline: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None
    workflow: Optional[str] = None
    service_name: Optional[str] = None
    run_id: Optional[str] = None


class IngestedItem(BaseModel):
    id: str
    doc_id: str
    source: str
    content_type: str
    chunk_index: int
    text: str
    repo: Optional[str] = None
    pipeline: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None
    workflow: Optional[str] = None
    service_name: Optional[str] = None
    run_id: Optional[str] = None

class AskRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    min_relevance: float = Field(default=1.2, ge=0.0, description="Distance threshold for filtering weak matches")
    content_type: Optional[Literal["logs", "docs"]] = None
    source: Optional[str] = None
    model_hint: Optional[str] = None

    # Optional retrieval filters
    repo: Optional[str] = None
    pipeline: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None
    workflow: Optional[str] = None
    service_name: Optional[str] = None
    run_id: Optional[str] = None

    # Analysis mode
    analysis_mode: Optional[Literal["general", "cicd"]] = "general"


class RetrievedChunk(BaseModel):
    citation: str
    source: str
    content_type: str
    chunk_index: int
    text: str
    distance: Optional[float] = None
    repo: Optional[str] = None
    pipeline: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None
    workflow: Optional[str] = None
    service_name: Optional[str] = None
    run_id: Optional[str] = None


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


class FixSuggestion(BaseModel):
    """Structured suggestion for fixing a failure."""
    fix_type: str = Field(description="Category: file_missing, config_error, auth_error, etc.")
    auto_fix_possible: bool = Field(description="Whether automatic application is feasible")
    target_file: Optional[str] = Field(default=None, description="Primary file to modify (repo-relative path)")
    target_confidence: str = Field(default="Low", description="High / Medium / Low confidence that target file is correct")
    target_changes: Optional[List[Dict[str, str]]] = Field(default=None, description="Files to add/modify/delete with rationale")
    suggested_change: str = Field(description="Human-readable description of the change")
    why_this_fix: str = Field(description="Reasoning for selecting this fix")
    evidence_used: List[str] = Field(default_factory=list, description="Concrete evidence from logs/context")
    assumptions: List[str] = Field(default_factory=list, description="Assumptions required by this fix")
    verification_steps: Optional[List[Dict[str, str]]] = Field(default=None, description="Verification steps with expected confirmation signals")
    alternatives_considered: List[str] = Field(default_factory=list, description="Alternative fix options considered")
    patch_text: Optional[str] = Field(default=None, description="Unified diff format showing exact changes")
    workflow: Optional[List[Dict[str, str]]] = Field(default=None, description="Step-by-step workflow with 'step' and 'command' fields")
    safe_to_auto_apply: bool = Field(description="True if fix can be safely auto-applied")
    confidence: str = Field(description="High / Medium / Low")
    requires_review: bool = Field(description="True if human review is required before applying")


class SuggestFixResponse(BaseModel):
    """Response for /suggest-fix endpoint with structured fix metadata."""
    diagnosis: str = Field(description="One-sentence root cause")
    fix_suggestions: List[FixSuggestion] = Field(description="Ordered list of fix options")
    prompt_version: str
    retrieved: List[RetrievedChunk]
    apply_mode: bool = Field(description="If true, fixes will be auto-applied; if false, only suggested")
    usage: Optional[Dict[str, Any]] = None

    embed_tokens: int = 0
    embed_cost_usd: float = 0.0
    chat_prompt_tokens: int = 0
    chat_completion_tokens: int = 0
    chat_cost_usd: float = 0.0
    total_cost_usd: float = 0.0

class SuggestFixRequest(BaseModel):
    question: str
    top_k: int = Field(default=5, ge=1, le=20)
    min_relevance: float = Field(default=1.2, ge=0.0, description="Distance threshold for filtering weak matches")
    apply_mode: bool = Field(default=False, description="If true, fixes will be auto-applied; if false, only suggested")

    # Optional retrieval filters
    repo: Optional[str] = None
    pipeline: Optional[str] = None
    environment: Optional[str] = None
    status: Optional[str] = None
    workflow: Optional[str] = None
    service_name: Optional[str] = None
    run_id: Optional[str] = None

    model_hint: Optional[str] = None


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


# ---------------------------
# Helpers
# ---------------------------
def chunk_docs(text: str, chunk_size: int, overlap: int) -> List[str]:
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

    if len(chunks) == 1 and len(chunks[0]) > chunk_size:
        return [
            text[i : i + chunk_size].strip()
            for i in range(0, len(text), max(1, chunk_size - overlap))
            if text[i : i + chunk_size].strip()
        ]

    return chunks


def chunk_logs(text: str, max_chars: int, overlap_lines: int = 5) -> List[str]:
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
            cur = cur[-overlap_lines:] if overlap_lines > 0 else []
            cur_len = sum(len(x) + 1 for x in cur)

        cur.append(ln)
        cur_len += ln_len

    if cur:
        chunks.append("\n".join(cur))

    return chunks


def embed_texts(texts: List[str]) -> Tuple[List[List[float]], int]:
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set")

    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    vectors = [item.embedding for item in resp.data]

    prompt_tokens = 0
    if getattr(resp, "usage", None) and getattr(resp.usage, "prompt_tokens", None) is not None:
        prompt_tokens = int(resp.usage.prompt_tokens)

    return vectors, prompt_tokens


# ---------------------------
# Endpoints
# ---------------------------
@router.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "model": OPENAI_MODEL,
        "embed_model": EMBED_MODEL,
        "prompt_version": PROMPT_VERSION,
        "chroma_dir": CHROMA_DIR,
    }


@router.post("/chat")
def chat(req: ChatRequest):
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set")

    request_id = str(uuid.uuid4())

    try:
        messages = [
            {"role": "system", "content": "You are a helpful DevOps assistant."},
            {"role": "user", "content": req.prompt},
        ]

        logger.info(json.dumps({
            "event": "chat_request_start",
            "request_id": request_id,
            "endpoint": "/chat",
            "model": OPENAI_MODEL,
        }))

        resp = generate_via_router(
            messages=messages,
            model_hint=OPENAI_MODEL,
            request_id=request_id,
            purpose="chat",
        )

        answer_text = resp.get("output_text", "")
        usage = resp.get("usage", {}) or {}

        chat_in = int(usage.get("input_tokens", 0) or 0)
        chat_out = int(usage.get("output_tokens", 0) or 0)
        chat_cost = float(usage.get("cost_usd", 0.0) or 0.0)

        add_cost(endpoint="/chat", model=OPENAI_MODEL, kind="chat", amount_usd=chat_cost)

        logger.info(json.dumps({
            "event": "chat_request_complete",
            "request_id": request_id,
            "endpoint": "/chat",
            "model": OPENAI_MODEL,
            "input_tokens": chat_in,
            "output_tokens": chat_out,
            "chat_cost_usd": round(chat_cost, 10),
        }))

        return {"answer": answer_text, "usage": usage, "request_id": request_id}
    except Exception as e:
        logger.error(json.dumps({
            "event": "chat_request_failed",
            "request_id": request_id,
            "endpoint": "/chat",
            "error": str(e),
        }))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ingest", response_model=IngestResponse)
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
        {
            "doc_id": doc_id,
            "source": req.source,
            "content_type": req.content_type,
            "chunk_index": i,
            "repo": req.repo or "",
            "pipeline": req.pipeline or "",
            "environment": req.environment or "",
            "status": req.status or "",
            "workflow": req.workflow or "",
            "service_name": req.service_name or "",
            "run_id": req.run_id or "",
        }
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


@router.post("/ingest-log", response_model=IngestResponse)
def ingest_log(req: IngestRequest):
    log_req = IngestRequest(
        source=req.source or "cicd",
        content_type="logs",
        text=req.text,
        chunk_size=req.chunk_size,
        chunk_overlap=req.chunk_overlap,
        repo=req.repo,
        pipeline=req.pipeline,
        environment=req.environment,
        status=req.status,
        workflow=req.workflow,
        service_name=req.service_name,
        run_id=req.run_id,
    )
    return ingest(log_req)


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set")

    request_id = str(uuid.uuid4())

    logger.info(json.dumps({
        "event": "ask_request_start",
        "request_id": request_id,
        "endpoint": "/ask",
        "question": req.question,
        "top_k": req.top_k,
        "content_type": req.content_type,
        "source": req.source,
        "repo": req.repo,
        "pipeline": req.pipeline,
        "environment": req.environment,
        "status": req.status,
        "workflow": req.workflow,
        "service_name": req.service_name,
        "analysis_mode": req.analysis_mode,
        "model_hint": req.model_hint,
    }))

    q_vecs, q_embed_tokens = embed_texts([req.question])
    q_embed = q_vecs[0]

    embed_cost = cost_usd(EMBED_MODEL, input_tokens=q_embed_tokens, output_tokens=0)
    add_cost(endpoint="/ask", model=EMBED_MODEL, kind="embeddings", amount_usd=embed_cost)

    where_conditions = []
    if req.content_type:
        where_conditions.append({"content_type": req.content_type})
    if req.source:
        where_conditions.append({"source": req.source})
    if req.repo:
        where_conditions.append({"repo": req.repo})
    if req.pipeline:
        where_conditions.append({"pipeline": req.pipeline})
    if req.environment:
        where_conditions.append({"environment": req.environment})
    if req.status:
        where_conditions.append({"status": req.status})
    if req.workflow:
        where_conditions.append({"workflow": req.workflow})
    if req.service_name:
        where_conditions.append({"service_name": req.service_name})
    if req.run_id:
        where_conditions.append({"run_id": req.run_id})

    where = None
    if len(where_conditions) == 1:
        where = where_conditions[0]
    elif len(where_conditions) > 1:
        where = {"$and": where_conditions}

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
        meta = meta or {}
        if dist is not None and dist > req.min_relevance:
            continue

        source = meta.get("source", "unknown")
        content_type = meta.get("content_type", "docs")
        chunk_index = int(meta.get("chunk_index", -1))

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
                repo=meta.get("repo") or None,
                pipeline=meta.get("pipeline") or None,
                environment=meta.get("environment") or None,
                status=meta.get("status") or None,
                workflow=meta.get("workflow") or None,
                service_name=meta.get("service_name") or None,
                run_id=meta.get("run_id") or None,
            )
        )

        context_meta = {
            "repo": meta.get("repo", ""),
            "pipeline": meta.get("pipeline", ""),
            "environment": meta.get("environment", ""),
            "status": meta.get("status", ""),
            "workflow": meta.get("workflow", ""),
            "service_name": meta.get("service_name", ""),
            "run_id": meta.get("run_id", ""),
        }
        context_meta_str = " ".join(
            f"{k}={v}" for k, v in context_meta.items() if isinstance(v, str) and v
        )

        context_header = f"{citation} source={source} type={content_type} chunk={chunk_index}"
        if context_meta_str:
            context_header = f"{context_header} {context_meta_str}"

        context_parts.append(
            f"{context_header}\n{doc}"
        )

    if not retrieved:
        logger.info(json.dumps({
            "event": "ask_request_no_context",
            "request_id": request_id,
            "endpoint": "/ask",
        }))
        return AskResponse(
            answer="Insufficient context. Please ingest relevant data.",
            prompt_version=PROMPT_VERSION,
            retrieved=[],
            usage=None,
        )

    context = "\n\n".join(context_parts)

    if req.analysis_mode == "cicd":
        selected_system_prompt = CICD_SYSTEM_PROMPT
        selected_template = CICD_RAG_TEMPLATE
    else:
        selected_system_prompt = SYSTEM_PROMPT
        selected_template = RAG_TEMPLATE

    user_prompt = selected_template.format(
        prompt_version=PROMPT_VERSION,
        context=context,
        question=req.question,
    )

    try:
        messages = [
            {"role": "system", "content": selected_system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        resp = generate_via_router(
            messages=messages,
            model_hint=req.model_hint or OPENAI_MODEL,
            request_id=request_id,
            purpose="rag",
        )

        answer = resp.get("output_text", "")
        usage = resp.get("usage", {}) or {}

        chat_in = int(usage.get("input_tokens", 0) or 0)
        chat_out = int(usage.get("output_tokens", 0) or 0)
        chat_cost = float(usage.get("cost_usd", 0.0) or 0.0)

        add_cost(endpoint="/ask", model=OPENAI_MODEL, kind="chat", amount_usd=chat_cost)

        total = embed_cost + chat_cost

        logger.info(json.dumps({
            "event": "ask_request_complete",
            "request_id": request_id,
            "endpoint": "/ask",
            "model_hint": req.model_hint or OPENAI_MODEL,
            "retrieved_count": len(retrieved),
            "embed_tokens": q_embed_tokens,
            "chat_input_tokens": chat_in,
            "chat_output_tokens": chat_out,
            "chat_cost_usd": round(chat_cost, 10),
            "total_cost_usd": round(total, 10),
        }))

        return AskResponse(
            answer=answer,
            prompt_version=PROMPT_VERSION,
            retrieved=retrieved,
            usage=usage,
            embed_tokens=q_embed_tokens,
            embed_cost_usd=round(embed_cost, 10),
            chat_prompt_tokens=chat_in,
            chat_completion_tokens=chat_out,
            chat_cost_usd=round(chat_cost, 10),
            total_cost_usd=round(total, 10),
        )
    except Exception as e:
        logger.error(json.dumps({
            "event": "ask_request_failed",
            "request_id": request_id,
            "endpoint": "/ask",
            "error": str(e),
        }))
        raise HTTPException(status_code=502, detail=f"Inference failed: {e}")


@router.post("/suggest-fix", response_model=SuggestFixResponse)
def suggest_fix(req: SuggestFixRequest):
    """
    Generate structured fix suggestions for a failure.
    When apply_mode=true, fixes are marked for auto-application (future: PR creation).
    When apply_mode=false, suggestions are informational only.
    """
    if not client:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not set")

    request_id = str(uuid.uuid4())

    logger.info(json.dumps({
        "event": "suggest_fix_request_start",
        "request_id": request_id,
        "endpoint": "/suggest-fix",
        "question": req.question[:100],
        "apply_mode": req.apply_mode,
    }))

    q_vecs, q_embed_tokens = embed_texts([req.question])
    q_embed = q_vecs[0]

    embed_cost = cost_usd(EMBED_MODEL, input_tokens=q_embed_tokens, output_tokens=0)
    add_cost(endpoint="/suggest-fix", model=EMBED_MODEL, kind="embeddings", amount_usd=embed_cost)

    where_conditions = []
    if req.repo:
        where_conditions.append({"repo": req.repo})
    if req.pipeline:
        where_conditions.append({"pipeline": req.pipeline})
    if req.environment:
        where_conditions.append({"environment": req.environment})
    if req.status:
        where_conditions.append({"status": req.status})
    if req.workflow:
        where_conditions.append({"workflow": req.workflow})
    if req.service_name:
        where_conditions.append({"service_name": req.service_name})
    if req.run_id:
        where_conditions.append({"run_id": req.run_id})

    where = None
    if len(where_conditions) == 1:
        where = where_conditions[0]
    elif len(where_conditions) > 1:
        where = {"$and": where_conditions}

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
        meta = meta or {}
        if dist is not None and dist > req.min_relevance:
            continue

        source = meta.get("source", "unknown")
        content_type = meta.get("content_type", "docs")
        chunk_index = int(meta.get("chunk_index", -1))

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
                repo=meta.get("repo") or None,
                pipeline=meta.get("pipeline") or None,
                environment=meta.get("environment") or None,
                status=meta.get("status") or None,
                workflow=meta.get("workflow") or None,
                service_name=meta.get("service_name") or None,
                run_id=meta.get("run_id") or None,
            )
        )

        context_meta = {
            "repo": meta.get("repo", ""),
            "pipeline": meta.get("pipeline", ""),
            "environment": meta.get("environment", ""),
            "status": meta.get("status", ""),
            "workflow": meta.get("workflow", ""),
            "service_name": meta.get("service_name", ""),
            "run_id": meta.get("run_id", ""),
        }
        context_meta_str = " ".join(
            f"{k}={v}" for k, v in context_meta.items() if isinstance(v, str) and v
        )

        context_header = f"{citation} source={source} type={content_type} chunk={chunk_index}"
        if context_meta_str:
            context_header = f"{context_header} {context_meta_str}"

        context_parts.append(
            f"{context_header}\n{doc}"
        )

    if not retrieved:
        logger.info(json.dumps({
            "event": "suggest_fix_request_no_context",
            "request_id": request_id,
            "endpoint": "/suggest-fix",
        }))
        return SuggestFixResponse(
            diagnosis="Insufficient context to suggest fixes.",
            fix_suggestions=[],
            prompt_version=PROMPT_VERSION,
            retrieved=[],
            apply_mode=req.apply_mode,
            usage=None,
        )

    try:
        context = "\n\n".join(context_parts)

        fix_prompt = FIX_SUGGESTION_TEMPLATE.format(
            prompt_version=PROMPT_VERSION,
            context=context,
            question=req.question,
        )

        messages = [
            {"role": "system", "content": FIX_SUGGESTION_SYSTEM_PROMPT},
            {"role": "user", "content": fix_prompt},
        ]

        resp = generate_via_router(
            messages=messages,
            model_hint=req.model_hint or OPENAI_MODEL,
            request_id=request_id,
            purpose="suggest_fix",
        )

        answer_text = resp.get("output_text", "")
        usage = resp.get("usage", {}) or {}

        chat_in = int(usage.get("input_tokens", 0) or 0)
        chat_out = int(usage.get("output_tokens", 0) or 0)
        chat_cost = float(usage.get("cost_usd", 0.0) or 0.0)

        add_cost(endpoint="/suggest-fix", model=OPENAI_MODEL, kind="chat", amount_usd=chat_cost)
        total = embed_cost + chat_cost

        diagnosis = "Unable to determine diagnosis."
        fix_suggestions: List[FixSuggestion] = []

        logger.info(json.dumps({
            "event": "suggest_fix_raw_response",
            "request_id": request_id,
            "response_length": len(answer_text),
            "response_preview": answer_text[:300],
        }))

        lines = answer_text.split("\n")
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if line_stripped.startswith("DIAGNOSIS:"):
                diagnosis = line_stripped.replace("DIAGNOSIS:", "").strip()
                logger.info(json.dumps({
                    "event": "suggest_fix_extracted_diagnosis",
                    "request_id": request_id,
                    "diagnosis": diagnosis,
                }))
            elif line_stripped.startswith("FIXES:"):
                try:
                    json_str = line_stripped.replace("FIXES:", "").strip()
                    if not json_str and i + 1 < len(lines):
                        json_str = "\n".join(lines[i+1:])
                    json_start = json_str.find("[")
                    json_end = json_str.rfind("]")
                    if json_start >= 0 and json_end > json_start:
                        json_str = json_str[json_start:json_end+1]
                        fix_list = json.loads(json_str)
                        for fix_obj in fix_list:
                            suggestion = FixSuggestion(
                                fix_type=fix_obj.get("fix_type", "unknown"),
                                auto_fix_possible=fix_obj.get("auto_fix_possible", False),
                                target_file=fix_obj.get("target_file"),
                                target_confidence=fix_obj.get("target_confidence", "Low"),
                                target_changes=fix_obj.get("target_changes"),
                                suggested_change=fix_obj.get("suggested_change", ""),
                                why_this_fix=fix_obj.get("why_this_fix", "Reasoning not provided"),
                                evidence_used=fix_obj.get("evidence_used", []) or [],
                                assumptions=fix_obj.get("assumptions", []) or [],
                                verification_steps=fix_obj.get("verification_steps"),
                                alternatives_considered=fix_obj.get("alternatives_considered", []) or [],
                                patch_text=fix_obj.get("patch_text"),
                                workflow=fix_obj.get("workflow"),
                                safe_to_auto_apply=fix_obj.get("safe_to_auto_apply", False),
                                confidence=fix_obj.get("confidence", "Low"),
                                requires_review=fix_obj.get("requires_review", False),
                            )
                            fix_suggestions.append(suggestion)
                        logger.info(json.dumps({
                            "event": "suggest_fix_extracted_fixes",
                            "request_id": request_id,
                            "fix_count": len(fix_suggestions),
                        }))
                    else:
                        logger.warning(json.dumps({
                            "event": "suggest_fix_no_json_found",
                            "request_id": request_id,
                            "line_content": json_str[:100],
                        }))
                except (json.JSONDecodeError, ValueError) as parse_err:
                    logger.warning(json.dumps({
                        "event": "suggest_fix_parse_error",
                        "request_id": request_id,
                        "error": str(parse_err),
                    }))

        logger.info(json.dumps({
            "event": "suggest_fix_request_complete",
            "request_id": request_id,
            "endpoint": "/suggest-fix",
            "fix_count": len(fix_suggestions),
            "apply_mode": req.apply_mode,
            "embed_tokens": q_embed_tokens,
            "chat_input_tokens": chat_in,
            "chat_output_tokens": chat_out,
            "chat_cost_usd": round(chat_cost, 10),
            "total_cost_usd": round(total, 10),
        }))

        return SuggestFixResponse(
            diagnosis=diagnosis,
            fix_suggestions=fix_suggestions,
            prompt_version=PROMPT_VERSION,
            retrieved=retrieved,
            apply_mode=req.apply_mode,
            usage=usage,
            embed_tokens=q_embed_tokens,
            embed_cost_usd=round(embed_cost, 10),
            chat_prompt_tokens=chat_in,
            chat_completion_tokens=chat_out,
            chat_cost_usd=round(chat_cost, 10),
            total_cost_usd=round(total, 10),
        )
    except Exception as e:
        logger.error(json.dumps({
            "event": "suggest_fix_request_failed",
            "request_id": request_id,
            "endpoint": "/suggest-fix",
            "error": str(e),
        }))
        raise HTTPException(status_code=502, detail=f"Fix suggestion failed: {e}")


@router.get("/sources", response_model=List[SourceSummary])
def list_sources(limit: int = 5000):
    data = collection.get(include=["metadatas"], limit=limit)
    metadatas = data.get("metadatas", []) or []

    counts: Dict[tuple, int] = {}
    for m in metadatas:
        src = m.get("source", "unknown")
        ctype = m.get("content_type", "unknown")
        key = (src, ctype)
        counts[key] = counts.get(key, 0) + 1

    out = [
        SourceSummary(source=src, content_type=ctype, chunks=n)
        for (src, ctype), n in sorted(counts.items(), key=lambda x: (x[0][0], x[0][1]))
    ]
    return out


@router.get("/ingested", response_model=List[IngestedItem])
def list_ingested(
    limit: int = 200,
    source: Optional[str] = None,
    content_type: Optional[Literal["logs", "docs"]] = None,
    doc_id: Optional[str] = None,
    run_id: Optional[str] = None,
):
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
                repo=meta.get("repo", ""),
                pipeline=meta.get("pipeline", ""),
                environment=meta.get("environment", ""),
                status=meta.get("status", ""),
                workflow=meta.get("workflow", ""),
                service_name=meta.get("service_name", ""),
                run_id=meta.get("run_id", ""),
            )
        )

    out.sort(key=lambda x: (x.source, x.content_type, x.doc_id, x.chunk_index))
    return out


@router.get("/costs")
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


@router.delete("/reset")
def reset_collection(confirm: bool = False):
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to reset")

    chroma_client.delete_collection("devops_knowledge")
    global collection
    collection = chroma_client.get_or_create_collection(name="devops_knowledge")
    return {"status": "ok", "message": "collection reset"}


@router.delete("/delete_source")
def delete_source(source: str):
    data = collection.get(where={"source": source}, include=["metadatas"])
    ids = data.get("ids", []) or []
    if not ids:
        return {"status": "ok", "deleted": 0, "source": source}

    collection.delete(ids=ids)
    return {"status": "ok", "deleted": len(ids), "source": source}