import json
import sys
import requests

BASE_URL = "http://localhost:8000"

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
        question = c["question"]
        filters = c.get("filters", {}) or {}
        must_contain_any = c.get("must_contain_any", []) or []
        must_cite = bool(c.get("must_cite", False))

        payload = {"question": question, "top_k": 5, **filters}

        r = requests.post(f"{BASE_URL}/ask", json=payload, timeout=60)
        if r.status_code != 200:
            print(f"[{name}] ❌ HTTP {r.status_code}: {r.text}")
            failed += 1
            continue

        data = r.json()
        answer = data.get("answer", "")

        ok = True
        if must_contain_any:
            if not any(s.lower() in answer.lower() for s in must_contain_any):
                print(f"[{name}] ❌ missing expected content. Needed one of: {must_contain_any}")
                ok = False

        if must_cite:
            if "[" not in answer or "]" not in answer:
                print(f"[{name}] ❌ expected citations like [1] in answer")
                ok = False

        if ok:
            print(f"[{name}] ✅ PASS")
            passed += 1
        else:
            print(f"[{name}] ❌ FAIL\nAnswer:\n{answer}\n")
            failed += 1

    print(f"\nResults: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 2)

if __name__ == "__main__":
    main()