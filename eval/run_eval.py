import json
import sys
import requests

BASE_URL = "http://localhost:8000"


def get_path(data, path: str):
    current = data
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        else:
            return None
    return current


def has_nonempty_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) > 0
    return True

def fail(msg: str):
    print(f"FAIL: {msg}")
    sys.exit(1)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "eval/golden.json"
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    passed = 0
    failed = 0

    for c in cases:
        name = c.get("name", "unnamed")
        endpoint = c.get("endpoint", "ask")
        question = c["question"]
        filters = c.get("filters", {}) or {}
        must_contain_any = c.get("must_contain_any", []) or []
        must_not_contain = c.get("must_not_contain", []) or []
        must_cite = bool(c.get("must_cite", False))
        required_top_level_keys = c.get("required_top_level_keys", []) or []
        nonempty_paths = c.get("nonempty_paths", []) or []
        min_fix_count = int(c.get("min_fix_count", 0) or 0)

        payload = {"question": question, "top_k": 5, **filters}

        r = requests.post(f"{BASE_URL}/{endpoint}", json=payload, timeout=60)
        if r.status_code != 200:
            print(f"[{name}] ❌ HTTP {r.status_code}: {r.text}")
            failed += 1
            continue

        data = r.json()
        answer = data.get("answer", "") if endpoint == "ask" else data.get("diagnosis", "")

        ok = True
        for key in required_top_level_keys:
            if key not in data:
                print(f"[{name}] ❌ missing top-level key: {key}")
                ok = False

        for path in nonempty_paths:
            value = get_path(data, path)
            if not has_nonempty_value(value):
                print(f"[{name}] ❌ expected non-empty path: {path}")
                ok = False

        if must_contain_any:
            if not any(s.lower() in answer.lower() for s in must_contain_any):
                print(f"[{name}] ❌ missing expected content. Needed one of: {must_contain_any}")
                ok = False

        if must_not_contain:
            if any(s.lower() in answer.lower() for s in must_not_contain):
                print(f"[{name}] ❌ response contained forbidden text: {must_not_contain}")
                ok = False

        if must_cite:
            if "[" not in answer or "]" not in answer:
                print(f"[{name}] ❌ expected citations like [1] in answer")
                ok = False

        if endpoint == "suggest-fix":
            fixes = data.get("fix_suggestions", []) or []
            if len(fixes) < min_fix_count:
                print(f"[{name}] ❌ expected at least {min_fix_count} fix suggestions, got {len(fixes)}")
                ok = False

        if ok:
            print(f"[{name}] ✅ PASS")
            passed += 1
        else:
            print(f"[{name}] ❌ FAIL\nResponse:\n{json.dumps(data, indent=2)}\n")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 2)

if __name__ == "__main__":
    main()