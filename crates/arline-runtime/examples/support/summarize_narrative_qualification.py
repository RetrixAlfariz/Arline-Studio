"""Source-deduplicated R5A summary and blinded review packet; no model calls."""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path


def summary(report, fixture):
    cases = {q["id"]: q for q in fixture["queries"]}
    result = {}
    for arm in ("legacy", "scope_fts", "bekko_diagnostic", "hybrid_rrf"):
        all_rows = [s for s in report["samples"] if s["arm"] == arm and s["scenario"] == "complete"]
        rows = [s for s in all_rows if s["repeat"] == 0]
        avg = lambda k, selected=rows: statistics.mean(s["metrics"][k] for s in selected
                                                     if s["metrics"].get(k) is not None)
        exact = [s for s in rows if "exact_name" in cases[s["query_id"]]["categories"] and not cases[s["query_id"]]["no_answer"]]
        no = [s for s in rows if cases[s["query_id"]]["no_answer"]]
        current = [s for s in rows if set(cases[s["query_id"]]["categories"]) & {"current_state", "state"}]
        temporal = [s for s in rows if set(cases[s["query_id"]]["categories"]) & {"historical", "history", "temporal", "time", "nested_fork", "branch"}]
        ids = {q: {tuple(s["metrics"]["source_ids"]) for s in all_rows if s["query_id"] == q} for q in cases}
        latency = sorted(s["latency_ms"] for s in all_rows)
        result[arm] = {
            "unique_queries": len(rows), "timed_samples": len(all_rows),
            **{k: avg(k) for k in ("recall_at_5", "recall_at_10", "mrr_at_10", "ndcg_at_10")},
            "exact_name_cases": len(exact), "exact_name_recall_at_5": avg("recall_at_5", exact) if exact else None,
            "current_state_cases": len(current), "current_state_evidence_recall_at_5": avg("recall_at_5", current) if current else None,
            "temporal_cases": len(temporal), "temporal_evidence_recall_at_5": avg("recall_at_5", temporal) if temporal else None,
            "no_answer_cases": len(no), "no_answer_retrieval_abstention_rate": avg("no_answer_abstention_correct", no) if no else None,
            "forbidden_source_selections": sum(s["metrics"]["forbidden_sources"] for s in rows),
            "scope_oracle_violations": sum(s["independent_scope_oracle_violations"] for s in rows),
            "contradicted_source_selections": sum(s["metrics"]["contradicted_sources"] for s in rows),
            "selected_unique_source_slots": sum(s["metrics"]["source_count"] for s in rows),
            "unjudged_source_slots": sum(s["metrics"]["unjudged_sources"] for s in rows),
            "nondeterministic_queries": [q for q, orders in ids.items() if len(orders) > 1],
            "latency_ms": {"p50": statistics.median(latency), **{f"p{int(p*100)}": latency[math.ceil(len(latency)*p)-1] for p in (.95, .99)}},
        }
    return {"split": report["split"], "fixture_sha256": report["fixture_sha256"], "arms": result,
            "degradation": [s for s in report["samples"] if s["scenario"] != "complete"]}


def packet(report, fixture):
    cases = {q["id"]: q for q in fixture["queries"]}
    docs = {d["id"]: d for d in fixture["documents"]}
    public, key = [], []
    for s in report["generations"]:
        if s.get("refused"):
            continue
        case = cases[s["query_id"]]
        code = hashlib.sha256(f'{report["split"]}/{s["arm"]}/{s["query_id"]}'.encode()).hexdigest()[:12]
        output = s["provider"].get("output", [])
        text = "\n".join(o.get("content", "") for o in output if o.get("type") == "message")
        public.append({"review_id": code, "split": report["split"], "query_id": s["query_id"],
                       "query": case["query"], "scope": case["scope"], "gold_answer": case["expected_answer"],
                       "no_answer": case["no_answer"], "mandatory_canon": fixture.get("canon_constraints", []),
                       "gold_sources": [{"id": i, "text": docs[i]["text"]} for i in case["relevant"]],
                       "writer_retained_sources": s["selected_source_ids"], "writer_retained_evidence": s.get("writer_retained_evidence", []), "scene": text,
                       "rubric": {"factual_correct": None, "continuity_correct": None,
                                  "canon_preserved": None, "abstention_correct": None,
                                  "unsupported_claims": None, "notes": "Awaiting independent adjudication; human separately required"}})
        key.append({"review_id": code, "arm": s["arm"], "query_id": s["query_id"]})
    public.sort(key=lambda x: x["review_id"])
    return public, key


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--fixture", type=Path, required=True)
    p.add_argument("--out-prefix", type=Path, required=True)
    args = p.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    raw = args.fixture.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == report["fixture_sha256"], "fixture changed after measurement"
    fixture = json.loads(raw.decode("utf-8"))
    review, key = packet(report, fixture)
    for suffix, value in (("-summary.json", summary(report, fixture)), ("-blind-review.json", review), ("-blind-key.json", key)):
        with Path(str(args.out_prefix) + suffix).open("x", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
    print(json.dumps({"split": report["split"], "review_cases": len(review), "human_review": "pending"}))
