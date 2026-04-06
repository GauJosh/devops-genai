#!/usr/bin/env python3
import argparse
import json
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.request
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def run_cmd(command: List[str], cwd: Path, timeout: int = 120) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration_ms = int((time.time() - started) * 1000)
        return {
            "command": " ".join(shlex.quote(part) for part in command),
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_ms": duration_ms,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.time() - started) * 1000)
        return {
            "command": " ".join(shlex.quote(part) for part in command),
            "exit_code": 124,
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + "\n[executor] command timed out",
            "duration_ms": duration_ms,
        }


def excerpt(text: str, limit: int = 600) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def post_json(url: str, payload: Dict[str, Any], timeout: int = 90) -> Dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {e.code} calling {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Failed to reach {url}: {e}") from e


def clean_github_failed_logs(raw: str) -> str:
    cleaned: List[str] = []
    skip_env_group = False

    timestamp_prefix = re.compile(r"^.*\d{4}-\d{2}-\d{2}T[^ ]*Z\s+")

    for original in raw.splitlines():
        line = original.replace("\r", "")
        line = line.lstrip("\ufeff")
        line = timestamp_prefix.sub("", line)

        if line == "env:":
            skip_env_group = True
            continue

        if skip_env_group and line == "##[endgroup]":
            skip_env_group = False
            continue

        if skip_env_group:
            continue

        line = line.replace("##[group]", "", 1)
        if line.startswith("##[error]"):
            line = line.replace("##[error]", "ERROR: ", 1)

        if line.startswith("shell: "):
            continue
        if line == "##[endgroup]":
            continue

        if line.strip():
            cleaned.append(line)

    return "\n".join(cleaned)


def get_latest_failed_run_id(github_repo: str, workflow_name: str) -> str:
    result = run_cmd(
        [
            "gh",
            "run",
            "list",
            "--repo",
            github_repo,
            "--workflow",
            workflow_name,
            "--status",
            "failure",
            "--limit",
            "1",
            "--json",
            "databaseId",
            "--jq",
            ".[0].databaseId",
        ],
        cwd=Path.cwd(),
    )
    if result["exit_code"] != 0:
        raise RuntimeError(f"Failed to list failed runs: {result['stderr']}")

    run_id = (result.get("stdout") or "").strip()
    if not run_id or run_id == "null":
        raise RuntimeError("No failed run found")
    return run_id


def fetch_failed_logs(github_repo: str, run_id: str) -> str:
    result = run_cmd(
        [
            "gh",
            "run",
            "view",
            run_id,
            "--repo",
            github_repo,
            "--log-failed",
        ],
        cwd=Path.cwd(),
        timeout=600,
    )
    if result["exit_code"] != 0:
        raise RuntimeError(f"Failed to fetch failed logs for run {run_id}: {result['stderr']}")

    return clean_github_failed_logs(result.get("stdout", ""))


def ingest_logs(
    agent_url: str,
    source: str,
    repo_name: str,
    pipeline: str,
    environment: str,
    status: str,
    workflow: str,
    service_name: str,
    run_id: str,
    log_text: str,
) -> Dict[str, Any]:
    payload = {
        "source": source,
        "repo": repo_name,
        "pipeline": pipeline,
        "environment": environment,
        "status": status,
        "workflow": workflow,
        "service_name": service_name,
        "content_type": "logs",
        "run_id": run_id,
        "text": log_text,
    }
    endpoint = agent_url.rstrip("/") + "/ingest-log"
    return post_json(endpoint, payload)


def detect_remote_repo_slug(repo_path: Path) -> Optional[str]:
    remote = run_cmd(["git", "config", "--get", "remote.origin.url"], cwd=repo_path)
    if remote["exit_code"] != 0:
        return None
    value = (remote.get("stdout") or "").strip()
    if not value:
        return None

    value = value.rstrip("/")
    value = re.sub(r"\.git$", "", value)
    match = re.search(r"github\.com[:/](?P<slug>[^/]+/[^/]+)$", value)
    if not match:
        return None
    return match.group("slug")


def ensure_target_repo_path(current_repo_path: Path, github_repo: Optional[str], workspace_root: Path) -> Path:
    if not github_repo:
        return current_repo_path

    current_slug = detect_remote_repo_slug(current_repo_path)
    if current_slug and current_slug.lower() == github_repo.lower():
        return current_repo_path

    repo_name = github_repo.split("/")[-1]
    target = workspace_root / repo_name
    workspace_root.mkdir(parents=True, exist_ok=True)

    if target.exists():
        if not (target / ".git").exists():
            raise RuntimeError(f"Target path exists but is not a git repo: {target}")
        fetch = run_cmd(["git", "fetch", "--prune", "--tags"], cwd=target)
        if fetch["exit_code"] != 0:
            raise RuntimeError(f"Failed to fetch existing checkout {target}: {fetch['stderr']}")
        return target

    clone = run_cmd(["gh", "repo", "clone", github_repo, str(target), "--", "--depth", "1"], cwd=workspace_root)
    if clone["exit_code"] != 0:
        raise RuntimeError(f"Failed to clone {github_repo} to {target}: {clone['stderr']}")
    return target


def build_suggest_payload(args: argparse.Namespace, runtime_context: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "question": args.question,
        "top_k": args.top_k,
        "min_relevance": args.min_relevance,
        "apply_mode": False,
        "content_type": args.content_type,
        "source": args.source,
        "use_kb": args.use_kb,
        "kb_source": args.kb_source,
        "kb_top_k": args.kb_top_k,
        "kb_min_relevance": args.kb_min_relevance,
        "runtime_context": runtime_context,
    }

    if args.repo:
        payload["repo"] = args.repo
    if args.pipeline:
        payload["pipeline"] = args.pipeline
    if args.workflow:
        payload["workflow"] = args.workflow
    if args.environment:
        payload["environment"] = args.environment
    if args.status:
        payload["status"] = args.status
    if args.service_name:
        payload["service_name"] = args.service_name
    if args.run_id:
        payload["run_id"] = args.run_id

    return payload


def derive_validation_commands(fix: Dict[str, Any]) -> List[str]:
    candidates: List[str] = []

    for item in fix.get("verification_steps") or []:
        step = str((item or {}).get("step", "")).lower()
        command = str((item or {}).get("command", "")).strip()
        if command and any(token in step for token in ["validate", "verify", "check", "test"]):
            candidates.append(command)

    for item in fix.get("workflow") or []:
        step = str((item or {}).get("step", "")).lower()
        command = str((item or {}).get("command", "")).strip()
        if command and any(token in step for token in ["validate", "verification", "check", "test"]):
            candidates.append(command)

    filtered: List[str] = []
    seen = set()
    blocked_tokens = [
        "gh pr",
        "git push",
        "git commit",
        "git checkout -b",
        "git merge",
        "git apply",
        "patch ",
        "write_text(",
        "sed -i",
        "perl -pi",
        "tee ",
        " >",
        " >>",
    ]

    allowed_validation_markers = [
        "python -m py_compile",
        "pytest",
        "python -m pytest",
        "tox",
        "grep -n",
        "sed -n",
        "cat ",
        "ls ",
        "test -f",
        "test -d",
    ]

    for cmd in candidates:
        lower_cmd = cmd.lower()
        if any(token in lower_cmd for token in blocked_tokens):
            continue
        if not any(marker in lower_cmd for marker in allowed_validation_markers):
            continue
        if cmd not in seen:
            seen.add(cmd)
            filtered.append(cmd)

    return filtered[:5]


def ensure_repo_ready(repo_path: Path, checkout_ref: Optional[str]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    checks.append(run_cmd(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_path))
    inside = checks[-1]["exit_code"] == 0 and "true" in checks[-1]["stdout"].strip().lower()
    if not inside:
        raise RuntimeError(f"{repo_path} is not a git work tree")

    checks.append(run_cmd(["git", "fetch", "--prune", "--tags"], cwd=repo_path))

    target_ref = checkout_ref
    if not target_ref:
        origin_head = run_cmd(
            ["git", "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
        )
        if origin_head["exit_code"] == 0:
            target_ref = (origin_head.get("stdout") or "").strip()

    if target_ref:
        checks.append(run_cmd(["git", "checkout", target_ref], cwd=repo_path))
        if checks[-1]["exit_code"] != 0:
            raise RuntimeError(f"Unable to checkout ref {target_ref}: {checks[-1]['stderr']}")

        checks.append(run_cmd(["git", "reset", "--hard", target_ref], cwd=repo_path))
        if checks[-1]["exit_code"] != 0:
            raise RuntimeError(f"Unable to reset to {target_ref}: {checks[-1]['stderr']}")

        checks.append(run_cmd(["git", "clean", "-fd"], cwd=repo_path))
        if checks[-1]["exit_code"] != 0:
            raise RuntimeError(f"Unable to clean repo at {repo_path}: {checks[-1]['stderr']}")

    checks.append(run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_path))
    if checks[-1]["exit_code"] != 0:
        raise RuntimeError(f"Unable to determine HEAD: {checks[-1]['stderr']}")

    commit_sha = checks[-1]["stdout"].strip()
    return {
        "checks": checks,
        "commit_sha": commit_sha,
    }


def collect_inspections(repo_path: Path, extra_inspect_cmds: List[str]) -> List[Dict[str, Any]]:
    base_commands: List[List[str]] = [
        ["git", "status", "--porcelain"],
        ["git", "branch", "--show-current"],
        ["git", "ls-tree", "-r", "--name-only", "HEAD"],
    ]

    inspections: List[Dict[str, Any]] = []
    for command in base_commands:
        result = run_cmd(command, cwd=repo_path)
        inspections.append(
            {
                "step": "inspection",
                "command": result["command"],
                "exit_code": result["exit_code"],
                "stdout_excerpt": excerpt(result.get("stdout", "")),
                "stderr_excerpt": excerpt(result.get("stderr", "")),
            }
        )

    for cmd in extra_inspect_cmds:
        result = run_cmd(["bash", "-lc", cmd], cwd=repo_path)
        inspections.append(
            {
                "step": "inspection",
                "command": cmd,
                "exit_code": result["exit_code"],
                "stdout_excerpt": excerpt(result.get("stdout", "")),
                "stderr_excerpt": excerpt(result.get("stderr", "")),
            }
        )

    return inspections


def collect_validations(repo_path: Path, validation_cmds: List[str]) -> List[Dict[str, Any]]:
    validations: List[Dict[str, Any]] = []
    for cmd in validation_cmds:
        result = run_cmd(["bash", "-lc", cmd], cwd=repo_path, timeout=600)
        validations.append(
            {
                "step": "validation",
                "command": cmd,
                "exit_code": result["exit_code"],
                "stdout_excerpt": excerpt(result.get("stdout", ""), limit=1200),
                "stderr_excerpt": excerpt(result.get("stderr", ""), limit=1200),
            }
        )
    return validations


def sanitize_branch_fragment(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower())
    clean = clean.strip("-._")
    return clean[:40] if clean else "ci-fix"


def format_fix_category(value: str) -> str:
    text = (value or "unknown").replace("_", " ").strip()
    if not text:
        return "Unknown"
    parts = [p for p in text.split(" ") if p]
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def yes_no(value: Any) -> str:
    return "Yes" if bool(value) else "No"


def build_branch_name(fix: Dict[str, Any]) -> str:
    branch_fragment = sanitize_branch_fragment(fix.get("fix_type", "ci-fix"))
    now = datetime.now(timezone.utc)
    date_part = now.strftime("%Y%m%d")
    timestamp_part = str(int(now.timestamp()))
    return f"auto/{branch_fragment}-{date_part}-{timestamp_part}"


def build_pr_title(title_prefix: str, fix: Dict[str, Any]) -> str:
    return f"{title_prefix}: {format_fix_category(str(fix.get('fix_type', 'ci-fix')))}"


def build_pr_body(
    diagnosis: str,
    fix: Dict[str, Any],
    runtime_context: Dict[str, Any],
    extra_body: str,
) -> str:
    lines: List[str] = []
    lines.append("## Created by DevOps GenAI Agent")
    lines.append("")
    lines.append("This PR was created automatically by the DevOps GenAI Agent after analyzing CI/CD failure context, repository state, and runtime validation evidence.")
    lines.append("")
    lines.append("## Diagnosis")
    lines.append(diagnosis or "No diagnosis provided.")
    lines.append("")
    lines.append("## Why fix works")
    lines.append(fix.get("why_this_fix", "No rationale provided."))
    lines.append("")
    lines.append("## Confidence")
    lines.append(f"- Overall: {fix.get('confidence', 'Unknown')}")
    lines.append(f"- Target: {fix.get('target_confidence', 'Unknown')}")
    lines.append(f"- Safe to Auto-Apply: {yes_no(fix.get('safe_to_auto_apply', False))}")
    lines.append(f"- Requires Review: {yes_no(fix.get('requires_review', True))}")
    lines.append("")
    lines.append("## Validation Steps")

    validation_runs = runtime_context.get("validation_runs") or []
    if validation_runs:
        for item in validation_runs:
            command = (item or {}).get("command", "")
            exit_code = (item or {}).get("exit_code", "")
            stdout_excerpt = excerpt(str((item or {}).get("stdout_excerpt", "")), limit=200)
            stderr_excerpt = excerpt(str((item or {}).get("stderr_excerpt", "")), limit=200)
            lines.append(f"- `{command}` → exit_code={exit_code}")
            if stdout_excerpt:
                lines.append(f"  - stdout: {stdout_excerpt}")
            if stderr_excerpt:
                lines.append(f"  - stderr: {stderr_excerpt}")
    else:
        verification_steps = fix.get("verification_steps") or []
        if verification_steps:
            for item in verification_steps:
                step = (item or {}).get("step", "step")
                command = (item or {}).get("command", "")
                expected_signal = (item or {}).get("expected_signal", "N/A")
                lines.append(f"- {step}: `{command}`")
                lines.append(f"  - expected: {expected_signal}")
        else:
            lines.append("- No validation steps were captured.")

    target_changes = fix.get("target_changes") or []
    if target_changes:
        lines.append("")
        lines.append("## Target Changes")
        for item in target_changes:
            action = (item or {}).get("action", "modify")
            file_path = (item or {}).get("file", "unknown")
            reason = (item or {}).get("reason", "no reason provided")
            lines.append(f"- [{action}] `{file_path}` — {reason}")

    evidence_used = fix.get("evidence_used") or []
    if evidence_used:
        lines.append("")
        lines.append("## Evidence Used")
        for item in evidence_used:
            lines.append(f"- {item}")

    if extra_body.strip():
        lines.append("")
        lines.append("## Additional Notes")
        lines.append(extra_body.strip())

    return "\n".join(lines).strip()


def print_fix_details(fix: Dict[str, Any]) -> None:
    print(f"Category: {format_fix_category(str(fix.get('fix_type', 'unknown')))}")
    print(f"Confidence: {fix.get('confidence', 'Low')}")
    print(f"Safe to Auto-Apply: {yes_no(fix.get('safe_to_auto_apply', False))}")
    print(f"Target Confidence: {fix.get('target_confidence', 'Unknown')}")
    print(f"Requires Review: {yes_no(fix.get('requires_review', True))}")

    target_file = fix.get("target_file")
    if target_file:
        print(f"Target: {target_file}")

    print(f"Change: {fix.get('suggested_change', '')}")
    print(f"Why This Fix: {fix.get('why_this_fix', 'N/A')}")

    target_changes = fix.get("target_changes") or []
    if target_changes:
        print("Target Changes:")
        for item in target_changes:
            action = (item or {}).get("action", "modify")
            file_path = (item or {}).get("file", "unknown")
            reason = (item or {}).get("reason", "no reason provided")
            print(f"  - [{action}] {file_path} -> {reason}")

    evidence_used = fix.get("evidence_used") or []
    if evidence_used:
        print("Evidence Used:")
        for item in evidence_used:
            print(f"  - {item}")

    assumptions = fix.get("assumptions") or []
    if assumptions:
        print("Assumptions:")
        for item in assumptions:
            print(f"  - {item}")

    verification_steps = fix.get("verification_steps") or []
    if verification_steps:
        print("Verification Steps:")
        for item in verification_steps:
            step = (item or {}).get("step", "step")
            command = (item or {}).get("command", "")
            expected_signal = (item or {}).get("expected_signal", "N/A")
            print(f"  - {step} [{command}] => expected: {expected_signal}")

    alternatives = fix.get("alternatives_considered") or []
    if alternatives:
        print("Alternatives Considered:")
        for item in alternatives:
            print(f"  - {item}")

    patch_text = (fix.get("patch_text") or "").strip()
    if patch_text:
        print("Patch:")
        for line in patch_text.splitlines():
            if line.strip().startswith("```"):
                continue
            print(f"  {line}")

    workflow = fix.get("workflow") or []
    if workflow:
        print("Workflow:")
        for item in workflow:
            step = (item or {}).get("step", "step")
            command = (item or {}).get("command", "")
            print(f"  - {step} [{command}]")


def should_auto_pr(
    fix: Dict[str, Any],
    runtime_context: Dict[str, Any],
    require_validation: bool,
) -> bool:
    checks = compute_safe_to_apply_checks(fix, runtime_context, require_validation=require_validation)
    return all(checks.values())


def compute_safe_to_apply_checks(
    fix: Dict[str, Any],
    runtime_context: Dict[str, Any],
    require_validation: bool,
) -> Dict[str, bool]:
    patch_text = (fix.get("patch_text") or "").strip()
    checks = {
        "confidence_high": str(fix.get("confidence", "")).lower() == "high",
        "target_confidence_high": str(fix.get("target_confidence", "")).lower() == "high",
        "safe_to_auto_apply_true": bool(fix.get("safe_to_auto_apply", False)),
        "repo_checked_out": bool(runtime_context.get("repo_checked_out")),
        "inspections_present": bool(runtime_context.get("inspections")),
        "validation_present": (bool(runtime_context.get("validation_runs")) if require_validation else True),
        "patch_present": bool(patch_text),
        "patch_is_unified_diff": bool(patch_text.startswith("--- ")),
    }
    return checks


def print_safe_to_apply_checklist(
    fix: Dict[str, Any],
    runtime_context: Dict[str, Any],
    require_validation: bool,
) -> None:
    checks = compute_safe_to_apply_checks(fix, runtime_context, require_validation=require_validation)
    print("\nSafe-to-Apply Checklist:")
    for key, ok in checks.items():
        label = key.replace("_", " ")
        mark = "✅" if ok else "❌"
        print(f"  {mark} {label}")


def normalize_unified_diff_hunks(patch_text: str) -> str:
    lines = patch_text.splitlines()
    out: List[str] = []
    i = 0

    hunk_re = re.compile(r"^@@\s*-(\d+)(?:,(\d+))?\s*\+(\d+)(?:,(\d+))?\s*@@")

    while i < len(lines):
        line = lines[i]
        match = hunk_re.match(line)
        if not match:
            out.append(line)
            i += 1
            continue

        old_start = int(match.group(1))
        new_start = int(match.group(3))
        i += 1

        hunk_lines: List[str] = []
        while i < len(lines):
            nxt = lines[i]
            if nxt.startswith("@@ ") or nxt.startswith("--- ") or nxt.startswith("diff --git "):
                break
            hunk_lines.append(nxt)
            i += 1

        old_count = 0
        new_count = 0
        for h in hunk_lines:
            if h.startswith("-"):
                old_count += 1
            elif h.startswith("+"):
                new_count += 1
            elif h.startswith(" ") or h == "":
                old_count += 1
                new_count += 1
            elif h.startswith("\\ No newline at end of file"):
                continue
            else:
                old_count += 1
                new_count += 1

        out.append(f"@@ -{old_start},{max(1, old_count)} +{new_start},{max(1, new_count)} @@")
        out.extend(hunk_lines)

    normalized = "\n".join(out).strip()
    return normalized + "\n"


def choose_remediation_command_from_workflow(workflow: List[Dict[str, Any]]) -> Optional[str]:
    blocked_tokens = ["gh pr", "git push", "git merge", "git commit", "rm -rf"]

    for item in workflow or []:
        step = str((item or {}).get("step", "")).lower()
        command = str((item or {}).get("command", "")).strip()
        if not command:
            continue
        lower_cmd = command.lower()
        if any(token in lower_cmd for token in blocked_tokens):
            continue
        if any(token in step for token in ["apply", "remedi", "fix"]):
            return command
    return None


def cleanup_transient_artifacts(repo_path: Path) -> None:
    patch_file = repo_path / ".suggest_fix.patch"
    if patch_file.exists():
        patch_file.unlink()

    for pyc_path in repo_path.rglob("*.pyc"):
        try:
            pyc_path.unlink()
        except OSError:
            pass

    for cache_dir in repo_path.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)


def apply_patch_and_open_pr(
    repo_path: Path,
    diagnosis: str,
    fix: Dict[str, Any],
    title_prefix: str,
    pr_body: str,
    runtime_context: Dict[str, Any],
) -> Dict[str, Any]:
    cleanup_transient_artifacts(repo_path)

    patch_text = (fix.get("patch_text") or "").strip()
    if patch_text:
        patch_file = repo_path / ".suggest_fix.patch"
        patch_file.write_text(patch_text + "\n", encoding="utf-8")

        check_apply = run_cmd(["git", "apply", "--check", str(patch_file)], cwd=repo_path)
        if check_apply["exit_code"] != 0:
            normalized_patch = normalize_unified_diff_hunks(patch_text)
            patch_file.write_text(normalized_patch, encoding="utf-8")
            check_apply = run_cmd(["git", "apply", "--check", str(patch_file)], cwd=repo_path)

        if check_apply["exit_code"] == 0:
            apply_result = run_cmd(["git", "apply", str(patch_file)], cwd=repo_path)
            if apply_result["exit_code"] != 0:
                raise RuntimeError(f"Patch apply failed: {apply_result['stderr']}")
        else:
            remediation_command = choose_remediation_command_from_workflow(fix.get("workflow") or [])
            if not remediation_command:
                raise RuntimeError(f"Patch check failed: {check_apply['stderr']}")
            remediation = run_cmd(["bash", "-lc", remediation_command], cwd=repo_path, timeout=600)
            if remediation["exit_code"] != 0:
                raise RuntimeError(
                    f"Patch check failed and remediation command failed: {remediation['stderr']}"
                )
    else:
        remediation_command = choose_remediation_command_from_workflow(fix.get("workflow") or [])
        if not remediation_command:
            raise RuntimeError("patch_text is empty and no safe remediation command found")
        remediation = run_cmd(["bash", "-lc", remediation_command], cwd=repo_path, timeout=600)
        if remediation["exit_code"] != 0:
            raise RuntimeError(f"Remediation command failed: {remediation['stderr']}")

    diff_check = run_cmd(["git", "status", "--porcelain"], cwd=repo_path)
    if diff_check["exit_code"] != 0:
        raise RuntimeError(f"Unable to inspect working tree changes: {diff_check['stderr']}")
    if not (diff_check.get("stdout") or "").strip():
        raise RuntimeError("No file changes detected after applying fix")

    cleanup_transient_artifacts(repo_path)

    branch_name = build_branch_name(fix)

    checkout = run_cmd(["git", "checkout", "-b", branch_name], cwd=repo_path)
    if checkout["exit_code"] != 0:
        raise RuntimeError(f"Failed to create branch: {checkout['stderr']}")

    cleanup_transient_artifacts(repo_path)
    run_cmd(["git", "add", "-A"], cwd=repo_path)
    commit_message = f"{title_prefix}: {fix.get('suggested_change', 'Apply suggested fix')}"
    commit = run_cmd(["git", "commit", "-m", commit_message], cwd=repo_path)
    if commit["exit_code"] != 0:
        raise RuntimeError(f"Git commit failed: {commit['stderr']}")

    push = run_cmd(["git", "push", "-u", "origin", branch_name], cwd=repo_path)
    if push["exit_code"] != 0:
        raise RuntimeError(f"Git push failed: {push['stderr']}")

    pr_title = build_pr_title(title_prefix, fix)
    rendered_pr_body = build_pr_body(
        diagnosis=diagnosis,
        fix=fix,
        runtime_context=runtime_context,
        extra_body=pr_body,
    )
    pr_create = run_cmd(
        ["gh", "pr", "create", "--title", pr_title, "--body", rendered_pr_body, "--head", branch_name],
        cwd=repo_path,
    )
    if pr_create["exit_code"] != 0:
        raise RuntimeError(f"gh pr create failed: {pr_create['stderr']}")

    return {
        "branch_name": branch_name,
        "pr_output": pr_create.get("stdout", "").strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Pure Python executor for /suggest-fix")
    parser.add_argument("--agent-url", required=True, help="Base URL for rag-service, e.g. http://rag-service:8000")
    parser.add_argument(
        "--question",
        default=(
            "Based on this failure, what are the actionable fixes? "
            "Provide one primary diagnosis and 1-3 structured fix suggestions "
            "with target files, commands, and safety assessment."
        ),
        help="Failure summary/question",
    )
    parser.add_argument("--repo-path", default=".", help="Path to checked-out repository")
    parser.add_argument(
        "--workspace-root",
        default=".executor-workspace",
        help="Workspace root for auto-cloned target repos when current repo does not match --github-repo",
    )
    parser.add_argument("--checkout-ref", default="", help="Optional git ref/SHA to checkout before analysis")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--min-relevance", type=float, default=2.0)
    parser.add_argument("--kb-top-k", type=int, default=3)
    parser.add_argument("--kb-min-relevance", type=float, default=1.6)
    parser.add_argument("--content-type", default="logs", choices=["logs", "docs"])
    parser.add_argument("--source", default="github-actions")
    parser.add_argument("--repo")
    parser.add_argument("--pipeline")
    parser.add_argument("--environment", default="ci")
    parser.add_argument("--status", default="failed")
    parser.add_argument("--workflow")
    parser.add_argument("--service-name", default="demo-app")
    parser.add_argument("--run-id")
    parser.add_argument("--use-kb", action="store_true", default=True)
    parser.add_argument("--kb-source", default="kb-playbook")
    parser.add_argument("--github-repo", help="GitHub repo in owner/name format for failed-run discovery")
    parser.add_argument("--github-workflow", help="GitHub workflow name for failed-run discovery")
    parser.add_argument(
        "--log-file",
        help="Optional file path containing failed logs to ingest (if omitted with github args, fetches via gh)",
    )
    parser.add_argument(
        "--ingest-logs",
        action="store_true",
        help="Ingest logs before suggest-fix. Automatically enabled when using github run discovery.",
    )
    parser.add_argument("--inspect-cmd", action="append", default=[], help="Extra inspection command (bash -lc)")
    parser.add_argument("--validation-cmd", action="append", default=[], help="Validation command to run before PR")
    parser.add_argument(
        "--create-pr",
        action="store_true",
        help="Deprecated: PR creation is automatic when safe-to-apply gates pass",
    )
    parser.add_argument(
        "--no-create-pr",
        action="store_true",
        help="Disable PR creation even when safe-to-apply gates pass",
    )
    parser.add_argument("--title-prefix", default="Automated CI Fix")
    parser.add_argument("--pr-body", default="Automated PR generated from /suggest-fix recommendation. No auto-merge.")
    args = parser.parse_args()

    script_start = time.time()

    if args.github_repo and not args.repo:
        args.repo = args.github_repo.split("/")[-1]
    if args.github_workflow and not args.pipeline:
        args.pipeline = args.github_workflow
    if args.github_workflow and not args.workflow:
        args.workflow = args.github_workflow

    repo_path = Path(args.repo_path).resolve()
    if not repo_path.exists():
        raise RuntimeError(f"repo-path does not exist: {repo_path}")

    workspace_root = Path(args.workspace_root).resolve()
    repo_path = ensure_target_repo_path(repo_path, args.github_repo, workspace_root)
    print(f"==> Using repository path: {repo_path}")

    should_discover_run = bool(args.github_repo and args.github_workflow and not args.run_id)
    if should_discover_run:
        print(f"==> Finding latest failed run for repo: {args.github_repo}")
        args.run_id = get_latest_failed_run_id(args.github_repo, args.github_workflow)
        print(f"==> Latest failed run id: {args.run_id}")

    should_ingest_logs = args.ingest_logs or bool(args.log_file) or bool(args.github_repo and args.run_id)
    if should_ingest_logs:
        if args.log_file:
            log_text = Path(args.log_file).read_text(encoding="utf-8")
        elif args.github_repo and args.run_id:
            print("==> Downloading failed logs from GitHub...")
            log_text = fetch_failed_logs(args.github_repo, args.run_id)
        else:
            raise RuntimeError("Log ingestion requested but no --log-file or --github-repo/--run-id provided")

        ingest_start = time.time()
        print("==> Ingesting logs into rag-service...")
        ingest_response = ingest_logs(
            agent_url=args.agent_url,
            source=args.source,
            repo_name=args.repo or "",
            pipeline=args.pipeline or "",
            environment=args.environment,
            status=args.status,
            workflow=args.workflow or "",
            service_name=args.service_name,
            run_id=args.run_id or "",
            log_text=log_text,
        )
        ingest_ms = int((time.time() - ingest_start) * 1000)
        print(f"Ingest response time: {ingest_ms}ms")
        print(
            f"Ingested chunks: {ingest_response.get('chunks_added', 'n/a')} "
            f"doc_id={ingest_response.get('doc_id', 'n/a')}"
        )

    checkout = ensure_repo_ready(repo_path=repo_path, checkout_ref=args.checkout_ref or None)
    inspections = collect_inspections(repo_path=repo_path, extra_inspect_cmds=args.inspect_cmd)
    validations = collect_validations(repo_path=repo_path, validation_cmds=args.validation_cmd)

    runtime_context: Dict[str, Any] = {
        "repo_checked_out": True,
        "repo_root": str(repo_path),
        "checkout_ref": args.checkout_ref or "HEAD",
        "commit_sha": checkout["commit_sha"],
        "inspections": inspections,
        "validation_runs": validations,
    }

    payload = build_suggest_payload(args, runtime_context)

    print("==> Suggesting fixes...")
    endpoint = args.agent_url.rstrip("/") + "/suggest-fix"
    suggest_start = time.time()
    response = post_json(endpoint, payload)
    suggest_ms = int((time.time() - suggest_start) * 1000)
    print(f"Suggest-fix response time: {round(suggest_ms / 1000)}s")

    fixes_first_pass = response.get("fix_suggestions", []) or []
    if fixes_first_pass and not runtime_context.get("validation_runs"):
        auto_validation_cmds = derive_validation_commands(fixes_first_pass[0])
        if auto_validation_cmds:
            print("==> Running auto-derived validation commands from suggested fix...")
            auto_validation_runs = collect_validations(repo_path=repo_path, validation_cmds=auto_validation_cmds)
            runtime_context["validation_runs"] = auto_validation_runs
            payload = build_suggest_payload(args, runtime_context)
            print("==> Re-evaluating /suggest-fix with validation evidence...")
            suggest_start_2 = time.time()
            response = post_json(endpoint, payload)
            suggest_ms_2 = int((time.time() - suggest_start_2) * 1000)
            print(f"Suggest-fix re-evaluation time: {round(suggest_ms_2 / 1000)}s")

    diagnosis = response.get("diagnosis", "")
    fixes = response.get("fix_suggestions", []) or []
    retrieved = response.get("retrieved", []) or []

    print("Diagnosis:")
    print(diagnosis)

    logs_chunks = len([x for x in retrieved if x.get("content_type") == "logs"])
    docs_chunks = len([x for x in retrieved if x.get("content_type") == "docs"])
    kb_chunks = len(
        [
            x
            for x in retrieved
            if x.get("content_type") == "docs" and x.get("source") == args.kb_source
        ]
    )
    sources = sorted({(x.get("source") or "unknown") for x in retrieved})
    print("\nContext Summary:")
    print(f"  Total Chunks: {len(retrieved)}")
    print(f"  Logs Chunks: {logs_chunks}")
    print(f"  Docs Chunks: {docs_chunks}")
    print(f"  KB Chunks ({args.kb_source}): {kb_chunks}")
    print(f"  Sources: {', '.join(sources) if sources else 'none'}")

    if fixes:
        print("\nSuggested Fixes:")
        for idx, fix in enumerate(fixes, start=1):
            if idx > 1:
                print("")
            print_fix_details(fix)
        print_safe_to_apply_checklist(fixes[0], runtime_context, require_validation=True)
    else:
        print("\nNo structured fixes generated.")

    if args.no_create_pr:
        print("\n[executor] PR creation disabled by --no-create-pr.")
        total_ms = int((time.time() - script_start) * 1000)
        print(f"\nTotal script runtime: {round(total_ms / 1000)}s")
        return 0

    if not fixes:
        print("\n[executor] No fixes returned. Skipping PR creation.")
        total_ms = int((time.time() - script_start) * 1000)
        print(f"\nTotal script runtime: {round(total_ms / 1000)}s")
        return 0

    selected_fix = fixes[0]
    allow_pr = should_auto_pr(
        fix=selected_fix,
        runtime_context=runtime_context,
        require_validation=True,
    )
    if not allow_pr:
        print("\n[executor] Policy gates not met; PR creation skipped.")
        print_safe_to_apply_checklist(selected_fix, runtime_context, require_validation=True)
        print(
            f"[executor] Gate summary: "
            f"confidence={selected_fix.get('confidence')}, "
            f"target_confidence={selected_fix.get('target_confidence')}, "
            f"safe_to_auto_apply={selected_fix.get('safe_to_auto_apply')}, "
            f"requires_review={selected_fix.get('requires_review')}, "
            f"has_patch={bool((selected_fix.get('patch_text') or '').strip())}, "
            f"validation_runs={len(runtime_context.get('validation_runs') or [])}"
        )
        total_ms = int((time.time() - script_start) * 1000)
        print(f"\nTotal script runtime: {round(total_ms / 1000)}s")
        return 0

    pr_info = apply_patch_and_open_pr(
        repo_path=repo_path,
        diagnosis=diagnosis,
        fix=selected_fix,
        title_prefix=args.title_prefix,
        pr_body=args.pr_body,
        runtime_context=runtime_context,
    )
    print("\n[executor] PR created successfully.")
    print(f"  branch: {pr_info['branch_name']}")
    if pr_info.get("pr_output"):
        print(f"  pr: {pr_info['pr_output']}")

    total_ms = int((time.time() - script_start) * 1000)
    print(f"\nTotal script runtime: {round(total_ms / 1000)}s")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[executor] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
