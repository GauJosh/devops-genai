"""
End-to-end pgvector proof:
  1. Ingest KB markdown
  2. Ingest a failure log
  3. Call /suggest-fix
  4. Check /sources
"""
import json, requests, pathlib, sys

BASE = "http://localhost:18000"

# ── Step 1: Ingest KB ──────────────────────────────────────────────────────────
print("=== Step 1: Ingest KB markdown ===")
text = pathlib.Path("docs/cicd-failure-playbook-kb.md").read_text(encoding="utf-8")
print(f"  KB file: {len(text)} chars")

r = requests.post(f"{BASE}/ingest", json={
    "source": "kb-playbook",
    "content_type": "docs",
    "text": text,
    "chunk_size": 1200,
    "chunk_overlap": 150,
    "repo": "cicd-demo",
    "pipeline": "failing-ci",
    "workflow": "failing-ci",
}, timeout=180)
print(f"  Status: {r.status_code}")
print(f"  Body:   {r.text}\n")
if r.status_code != 200:
    sys.exit(1)

# ── Step 2: Ingest failure log ─────────────────────────────────────────────────
print("=== Step 2: Ingest failure log ===")
r = requests.post(f"{BASE}/ingest-log", json={
    "source": "github-actions",
    "repo": "cicd-demo",
    "pipeline": "failing-ci",
    "environment": "ci",
    "status": "failed",
    "workflow": "failing-ci",
    "service_name": "demo-app",
    "content_type": "logs",
    "run_id": "local-proof-001",
    "text": (
        "Run app\n"
        "python app.py\n"
        "SyntaxError: expected ':'\n"
        "  File \"app.py\", line 14\n"
        "    def handle(req)\n"
        "               ^\n"
        "##[error]Process completed with exit code 1."
    ),
}, timeout=120)
print(f"  Status: {r.status_code}")
print(f"  Body:   {r.text}\n")
if r.status_code != 200:
    sys.exit(1)

# ── Step 3: /suggest-fix ──────────────────────────────────────────────────────
print("=== Step 3: /suggest-fix ===")
r = requests.post(f"{BASE}/suggest-fix", json={
    "question": "Based on the failure log excerpt, what is the root cause and exact first fix?",
    "top_k": 5,
    "content_type": "logs",
    "source": "github-actions",
    "repo": "cicd-demo",
    "pipeline": "failing-ci",
    "workflow": "failing-ci",
    "run_id": "local-proof-001",
    "analysis_mode": "cicd",
    "use_kb": True,
    "kb_source": "kb-playbook",
    "model_hint": "gpt-4o-mini",
}, timeout=240)
print(f"  Status: {r.status_code}")
try:
    body = r.json()
    print(json.dumps(body, indent=2))
except Exception:
    print(r.text)

# ── Step 4: /sources ──────────────────────────────────────────────────────────
print("\n=== Step 4: /sources ===")
r = requests.get(f"{BASE}/sources", timeout=30)
print(f"  Status: {r.status_code}")
try:
    print(json.dumps(r.json(), indent=2))
except Exception:
    print(r.text)
