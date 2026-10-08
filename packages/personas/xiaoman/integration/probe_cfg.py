"""Read-only probe: print integration config shape with secrets redacted."""
import json
import os

P = os.environ.get("ASUNA_INTEGRATION_CONFIG", "/integration/config.json")
c = json.load(open(P, encoding="utf-8"))


def redact(o, key=""):
    if isinstance(o, dict):
        return {k: redact(v, k) for k, v in o.items()}
    if isinstance(o, list):
        return [redact(v, key) for v in o]
    if isinstance(o, str):
        lk = key.lower()
        if any(s in lk for s in ("token", "password", "secret", "key")):
            return "<set len=%d>" % len(o)
        if len(o) > 80:
            return o[:80] + "..."
    return o


for k, v in c.items():
    if isinstance(v, dict):
        print("==", k, "->", json.dumps(redact(v), ensure_ascii=False, indent=1)[:2000])
    elif isinstance(v, list):
        print("==", k, "-> list of", len(v))
    else:
        print("==", k, "->", type(v).__name__)
