"""Read-only premeasurement validation; this is not prose or human review."""
import argparse
import hashlib
import json
from pathlib import Path


def allowed(doc, scope):
    if doc["semantic_status"] != "active":
        return False
    if doc["story_order"] > scope["story_order"] or doc["world_time"] > scope["world_time"]:
        return False
    if scope.get("pov_variant_id") and doc["authority"] == "author_only":
        return False
    have, want = doc["branch_id"], scope["branch_id"]
    return (have is None or have == want
            or have == "r5-main" and want in ("r5-fork", "r5-nested") and doc["story_order"] <= 12
            or have == "r5-fork" and want == "r5-nested" and doc["story_order"] <= 20)


def validate(path):
    raw = path.read_bytes()
    corpus = json.loads(raw.decode("utf-8"))
    docs = {d["id"]: d for d in corpus["documents"]}
    assert len(docs) == len(corpus["documents"]), "duplicate source IDs"
    ids = [q["id"] for q in corpus["queries"]]
    assert len(set(ids)) == len(ids), "duplicate query IDs"
    for doc in docs.values():
        assert doc["text"].strip(), doc["id"]
        assert 1 <= doc["story_order"] <= 31, "recorded-date encoding"
        assert not doc.get("visible_to"), "selective document visibility unsupported by harness"
    for q in corpus["queries"]:
        assert q["no_answer"] == (not q["relevant"]), q["id"]
        scope = q["scope"]
        assert scope["context_lens"] != "pov" or scope.get("pov_variant_id"), q["id"]
        assert not scope.get("pov_variant_id") or scope["pov_variant_id"] == "r5-pov", q["id"]
        for field in ("relevant", "forbidden", "contradicted"):
            assert len(q[field]) == len(set(q[field])), (q["id"], field)
            assert all(i in docs for i in q[field]), (q["id"], field)
        assert not set(q["relevant"]) & (set(q["forbidden"]) | set(q["contradicted"])), q["id"]
        assert all(allowed(docs[i], scope) for i in q["relevant"]), (q["id"], "ineligible gold")
        assert all(not allowed(docs[i], scope) for i in q["forbidden"]), (q["id"], "eligible forbidden")
    return {"file": path.as_posix(), "sha256": hashlib.sha256(raw).hexdigest(),
            "documents": len(docs), "words": sum(len(d["text"].split()) for d in docs.values()),
            "queries": len(ids), "continuity_probes": sum(q.get("continuity_probe", False) for q in corpus["queries"]),
            "human_review": "pending", "structural_and_gold_eligibility": "passed"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", nargs="+", type=Path)
    args = parser.parse_args()
    print(json.dumps([validate(p) for p in args.fixtures], indent=2))
