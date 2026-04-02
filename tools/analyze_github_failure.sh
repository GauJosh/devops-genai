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

# Writing to mktmp
echo "Fetching logs for run ID: $RUN_ID, repo id: $REPO and writing to temporary file: $TMP_LOG_FILE"
gh run view "$RUN_ID" \
  --repo "$REPO" \
  --log-failed|grep -inE "error|failed|exit|No such file|can't open file" > "$TMP_LOG_FILE"

echo "==> Logs:"
echo "$(cat $TMP_LOG_FILE)"
echo ""

echo "==> Ingesting logs into devops-genai..."

jq -Rs \
  --arg source "github-actions" \
  --arg repo_name "cicd-demo" \
  --arg pipeline "failing-ci" \
  --arg environment "ci" \
  --arg status "failed" \
  --arg workflow "failing-ci" \
  --arg service_name "demo-app" \
  --arg content_type "logs" \
  --arg run_id "$RUN_ID" \
  '{
    source: $source,
    repo: $repo_name,
    pipeline: $pipeline,
    environment: $environment,
    status: $status,
    workflow: $workflow,
    service_name: $service_name,
    content_type: $content_type,
    run_id: $run_id,
    text: .
  }' "$TMP_LOG_FILE" \
| curl -sS -X POST "${RAG_BASE_URL}/ingest-log" \
    -H "Content-Type: application/json" \
    -d @-

echo "Print exact text field sent to curl:"
jq -Rs \
  --arg source "github-actions" \
  --arg repo_name "cicd-demo" \
  --arg pipeline "failing-ci" \
  --arg environment "ci" \
  --arg status "failed" \
  --arg workflow "failing-ci" \
  --arg service_name "demo-app" \
  --arg content_type "logs" \
  --arg run_id "$RUN_ID" \
  '{
    source: $source,
    repo: $repo_name,
    pipeline: $pipeline,
    environment: $environment,
    status: $status,
    workflow: $workflow,
    service_name: $service_name,
    content_type: $content_type,
    run_id: $run_id,
    text: .
  }' "$TMP_LOG_FILE" | jq -r '.text'

echo
echo "==> Asking for analysis..."

curl -sS -X POST "${RAG_BASE_URL}/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Based on the failure log excerpt, what command failed, what is the immediate root cause, and what should be fixed first?",
    "top_k": 5,
    "source": "github-actions",
    "repo": "cicd-demo",
    "pipeline": "failing-ci",
    "environment": "ci",
    "status": "failed",
    "workflow": "failing-ci",
    "analysis_mode": "cicd",
    "model_hint": "gpt-4o-mini",
    "content_type": "logs",
    "min_relevance": 2.0,
    "run_id": "'"$RUN_ID"'"
  }'|jq -r '.answer'
echo