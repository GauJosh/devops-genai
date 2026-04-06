# CI/CD Failure Playbook KB (for RAG)

## Purpose
This playbook is designed for the `/ask` and `/suggest-fix` agent flows.
It provides evidence-first runbooks for common failure scenarios in `.github/workflows/failing-ci.yml`.

Agent policy this KB assumes:
- Verify workflow/config first
- Do not invent files/frameworks/content
- Prefer inspection + verification before mutation
- Only generate exact patch when evidence is sufficient

---

## Standard Triage Sequence (applies to all failures)
1. Identify failing step name and exact command from logs.
2. Confirm workflow command/path in `.github/workflows/failing-ci.yml`.
3. Confirm file/resource existence in repo.
4. Validate the specific tool runtime (python/pip/docker/flake8).
5. Apply smallest fix.
6. Validate fix locally (or with the same command) before proposing PR.

Reusable checks:
- `grep -n "Run app\|Install dependencies\|Docker build\|Lint code" .github/workflows/failing-ci.yml`
- `git ls-tree -r --name-only HEAD`
- `git log --oneline -- <file>`

---

## Failure 1: app.py missing (Run app step)
### Typical evidence
- `python app.py`
- `can't open file 'app.py'` or `No such file or directory`

### Verify first
- `grep -n "python app.py" .github/workflows/failing-ci.yml`
- `test -f app.py && echo exists || echo missing`
- `git log --oneline -- app.py | head -20`

### Decision logic
- If workflow path is wrong but file exists elsewhere: fix workflow path.
- If file existed and was deleted recently: restore from git history.
- If file never existed: do **not** generate guessed file content; require design intent.

### Suggested remediation
- Preferred: path correction or restore known file.
- Avoid: creating placeholder `app.py` with guessed code.

---

## Failure 2: Dockerfile uses invalid base image
### Typical evidence
- Docker build error pulling base image, e.g. `manifest unknown` / `pull access denied`.

### Verify first
- `grep -n "^FROM " Dockerfile`
- `grep -n "docker build" .github/workflows/failing-ci.yml`
- `docker build -t cicd-demo:latest .` (reproduce)

### Decision logic
- If `FROM test:1.2.3` (or invalid image) is present: modify Dockerfile base image.
- If workflow references wrong Dockerfile: fix workflow command first.

### Suggested remediation
- Update `FROM` to valid, approved base image.
- Validate by rerunning docker build command.

---

## Failure 3: requirements-prod.txt missing
### Typical evidence
- `pip install -r requirements-prod.txt`
- file-not-found error

### Verify first
- `grep -n "requirements-prod.txt\|pip install -r" .github/workflows/failing-ci.yml`
- `test -f requirements-prod.txt && echo exists || echo missing`
- `test -f requirements.txt && echo requirements.txt exists`

### Decision logic
- If workflow should use `requirements.txt`: update workflow.
- If `requirements-prod.txt` existed before: restore it.
- If neither is clear: request policy/intent; no guessed file creation.

---

## Failure 4: Invalid package version in requirements.txt
### Typical evidence
- `ERROR: Could not find a version that satisfies the requirement requests==999.999.999`

### Verify first
- `grep -n "requests==" requirements.txt`
- `python -m pip install -r requirements.txt` (reproduce)

### Suggested remediation
- Change invalid version to valid pinned version used by project policy.
- If policy unknown: use constraint range from internal standard, not arbitrary latest.

### Validation
- `python -m pip install -r requirements.txt`

---

## Failure 5: Python syntax error in app.py
### Typical evidence
- `File ".../app.py", line N`
- source line + caret
- `SyntaxError: expected ':'`

### Verify first
- `grep -n "python app.py" .github/workflows/failing-ci.yml`
- `sed -n '1,80p' app.py`

### Suggested remediation
- Apply minimal syntax correction to exact failing line.

### Patch format requirement
Use plain unified diff (no markdown fences), example:

--- a/app.py
+++ b/app.py
@@
-def main()
+def main():

### Validation
- `python -m py_compile app.py`
- `python app.py` (if safe)

---

## Failure 6: Missing Dockerfile.prod
### Typical evidence
- `open Dockerfile.prod: no such file or directory`

### Verify first
- `grep -n "docker build" .github/workflows/failing-ci.yml`
- `ls -la Dockerfile*`
- `git log --oneline -- Dockerfile.prod | head -20`

### Decision logic
- If workflow expects `Dockerfile.prod` but only `Dockerfile` exists: update workflow or introduce approved prod Dockerfile from template.
- If `Dockerfile.prod` existed and was deleted: restore.
- Avoid unapproved guessed Dockerfile content.

---

## Failure 7: Docker COPY failure due to missing files
### Typical evidence
- `COPY failed` / missing source path during build

### Verify first
- `grep -n "^COPY\|^ADD" Dockerfile`
- `git ls-tree -r --name-only HEAD | grep -E "<missing-path-pattern>"`
- Confirm `.dockerignore` is not excluding required path.

### Suggested remediation
- Fix COPY source path or include required file in build context.
- If file intentionally absent, adjust Dockerfile/build strategy.

---

## Failure 8: flake8 missing in lint step
### Typical evidence
- `flake8: command not found`

### Verify first
- `grep -n "flake8" .github/workflows/failing-ci.yml`
- `grep -n "flake8" requirements*.txt pyproject.toml setup.cfg`

### Suggested remediation
- Install lint deps before lint step, or run via tool manager (`python -m flake8` if package installed).
- Prefer pinned dev dependency in project config.

### Validation
- `python -m flake8 .`

---

## Output Contract for /suggest-fix
When evidence is sufficient:
- `target_file`: concrete file
- `target_confidence`: High/Medium
- `patch_text`: unified diff only
- `workflow`: must include verification -> remediation -> validation

When evidence is insufficient:
- `target_file`: null
- `target_confidence`: Low
- `patch_text`: null
- include explicit `assumptions` and extra `verification_steps`

---

## Safe Auto-Apply Policy
Set `safe_to_auto_apply=true` only when all are true:
1. exact target file and line are evidenced by logs/repo checks
2. minimal deterministic change (e.g., syntax character fix)
3. local validation command succeeds
4. no unresolved assumptions remain

Else set `safe_to_auto_apply=false` and require review.

---

## PR-Only Automation Guardrails
If auto-PR is enabled, open PR only (never merge) and include:
- diagnosis
- evidence used
- exact patch
- validation output
- residual risks/assumptions

Abort auto-PR when:
- target confidence is Low
- patch is null but mutation is proposed
- workflow/config verification not performed
- alternatives rely on unproven repository facts
