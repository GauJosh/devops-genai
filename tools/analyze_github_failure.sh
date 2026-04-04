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
  --log-failed \
  | awk '
    {
      line = $0
      sub(/^.*[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[^ ]*Z[[:space:]]+/, "", line)
      sub(/^﻿/, "", line)
      gsub(/\r/, "", line)

      if (line ~ /^env:$/) { skip=1; next }
      if (skip && line ~ /^##\[endgroup\]$/) { skip=0; next }
      if (skip) next

      sub(/^##\[group\]/, "", line)
      sub(/^##\[error\]/, "ERROR: ", line)

      if (line ~ /^shell: /) next
      if (line ~ /^##\[endgroup\]$/) next
      if (line != "") print line
    }
  ' > "$TMP_LOG_FILE"

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
echo ""
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

echo ""
echo "==> Asking for analysis..."

curl -sS -X POST "${RAG_BASE_URL}/ask" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Analyze this CI/CD failure and respond decisively. Identify the failure category, execution context (workflow/pipeline and failing step), immediate failure, one primary diagnosis, and the first fix to apply now. Avoid weak hedging unless evidence is insufficient. For commands, use repo-relative or local-safe paths, not ephemeral CI runner paths. If a file is missing, prefer verify/restore/correct-path guidance over creating an empty placeholder file unless the evidence explicitly shows a new scaffolded file is expected. Use this exact structure: Failure Category, Execution Context, Immediate Failure, Primary Diagnosis, Evidence, Fix First, Fallback if Fix Fails, Top 3 Verifications, Confidence.",
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

echo "==> Suggesting fixes..."

SUGGEST_RESPONSE="$(curl -sS -X POST "${RAG_BASE_URL}/suggest-fix" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Based on this failure, what are the actionable fixes? Provide one primary diagnosis and 1-3 structured fix suggestions with target files, commands, and safety assessment.",
    "top_k": 5,
    "source": "github-actions",
    "repo": "cicd-demo",
    "pipeline": "failing-ci",
    "environment": "ci",
    "status": "failed",
    "workflow": "failing-ci",
    "model_hint": "gpt-4o-mini",
    "apply_mode": false,
    "min_relevance": 2.0,
    "run_id": "'"$RUN_ID"'"
  }')"

echo "Diagnosis:"
if echo "$SUGGEST_RESPONSE" | jq empty >/dev/null 2>&1; then
  echo "$SUGGEST_RESPONSE" | jq -r '.diagnosis // "Unable to determine diagnosis"'
else
  echo "Invalid /suggest-fix response"
  echo "$SUGGEST_RESPONSE"
  exit 1
fi
echo ""

fix_count=$(echo "$SUGGEST_RESPONSE" | jq '.fix_suggestions | length' 2>/dev/null || echo 0)
if [[ "$fix_count" -gt 0 ]]; then
  echo "Suggested Fixes:"
  echo "$SUGGEST_RESPONSE" | jq -r '.fix_suggestions[] |
    "Category: \((.fix_type // "unknown")
      | gsub("_"; " ")
      | split(" ")
      | map(if length > 0 then (.[0:1] | ascii_upcase) + .[1:] else . end)
      | join(" "))\n" +
    "Confidence: \(.confidence)\n" +
    "Safe to Auto-Apply: \(if .safe_to_auto_apply then "Yes" else "No" end)\n" +
    "Target Confidence: \(.target_confidence // "Unknown")\n" +
    "Requires Review: \(if .requires_review then "Yes" else "No" end)\n" +
    (if (.target_file // "") != "" then "Target: \(.target_file)\n" else "" end) +
    "Change: \(.suggested_change)\n" +
    "Why This Fix: \(.why_this_fix // "N/A")\n" +
    (if (.target_changes // []) | length > 0 then
      "Target Changes:\n" + ((.target_changes // []) | map("  - [\(.action // "modify")] \(.file // "unknown") -> \(.reason // "no reason provided")") | join("\n")) + "\n"
     else ""
     end) +
    (if (.evidence_used // []) | length > 0 then
      "Evidence Used:\n" + ((.evidence_used // []) | map("  - " + .) | join("\n")) + "\n"
     else ""
     end) +
    (if (.assumptions // []) | length > 0 then
      "Assumptions:\n" + ((.assumptions // []) | map("  - " + .) | join("\n")) + "\n"
     else ""
     end) +
    (if (.verification_steps // []) | length > 0 then
      "Verification Steps:\n" + ((.verification_steps // []) | map("  - \(.step) [\(.command)] => expected: \(.expected_signal // "N/A")") | join("\n")) + "\n"
     else ""
     end) +
    (if (.alternatives_considered // []) | length > 0 then
      "Alternatives Considered:\n" + ((.alternatives_considered // []) | map("  - " + .) | join("\n")) + "\n"
     else ""
     end) +
    (if (.patch_text // "") != "" then
      "Patch:\n" + (.patch_text | split("\n") | map("  " + .) | join("\n")) + "\n"
     else ""
     end) +
    (if (.workflow // []) | length > 0 then
      "Workflow:\n" + ((.workflow // []) | map("  - \(.step) [\(.command)]") | join("\n")) + "\n"
     else ""
     end)
  '
else
  echo "No structured fixes generated."
fi
echo