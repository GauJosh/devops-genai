#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-GauJosh/cicd-demo}"
WORKFLOW_NAME="${2:-failing-ci}"
RAG_BASE_URL="${3:-http://localhost:18000}"

TMP_LOG_FILE="$(mktemp)"
trap 'rm -f "$TMP_LOG_FILE"' EXIT

echo "==> Finding latest failed run for repo: $REPO"

RUN_ID="$(gh run list \
  --repo "$REPO" \
  --workflow "$WORKFLOW_NAME" \
  --status failure \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')"

if [[ -z "${RUN_ID}" || "${RUN_ID}" == "null" ]]; then
  echo "No failed run found."
  exit 1
fi

echo "==> Latest failed run id: $RUN_ID"
echo "==> Downloading logs..."

gh run view "$RUN_ID" \
  --repo "$REPO" \
  --log > "$TMP_LOG_FILE"

echo "==> Ingesting logs into devops-genai..."

jq -Rs \
  --arg source "github-actions" \
  --arg repo_name "cicd-failure-demo" \
  --arg pipeline "failing-ci" \
  --arg environment "ci" \
  --arg status "failed" \
  --arg workflow "failing-ci" \
  --arg service_name "demo-app" \
  '{
    source: $source,
    repo: $repo_name,
    pipeline: $pipeline,
    environment: $environment,
    status: $status,
    workflow: $workflow,
    service_name: $service_name,
    text: .
  }' "$TMP_LOG_FILE" \
| curl -sS -X POST "${RAG_BASE_URL}/ingest-log" \
    -H "Content-Type: application/json" \
    -d @-

echo
echo "==> Asking for analysis..."

curl -sS -X POST "${RAG_BASE_URL}/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Why did this GitHub Actions workflow fail, what is the likely root cause, and what should I check first?",
    "top_k": 5,
    "source": "github-actions",
    "repo": "cicd-failure-demo",
    "pipeline": "failing-ci",
    "environment": "ci",
    "status": "failed",
    "workflow": "failing-ci",
    "analysis_mode": "cicd",
    "model_hint": "gpt-4o-mini"
  }'
echo