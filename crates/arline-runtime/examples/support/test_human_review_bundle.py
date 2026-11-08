"""Focused export checks against frozen local artifacts; no inference or DB."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import build_human_review_bundle as bundle

ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / ".codex-audit/retrieval-r5-20261107"
FIXTURES = ROOT / "crates/arline-runtime/tests/fixtures"
REPLAY = AUDIT / "human-review-context-replay.json"


class ReviewerBundleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.replay = bundle.load(REPLAY)
        cls.cases, cls.corpora, _ = bundle.make_cases(AUDIT, FIXTURES, cls.replay)

    def test_exact_provenance_blank_scores_and_no_rank_disclosure(self):
        originals = {c["review_id"]: c for split in ("development", "heldout")
                     for c in bundle.load(AUDIT / f"{split}-final-blind-review.json")}
        self.assertEqual(len(self.cases), 36)
        for case in self.cases:
            original = originals[case["review_id"]]
            self.assertEqual(case["generated_scene"], original["scene"])
            self.assertEqual(case["original_query"], original["query"])
            self.assertTrue(all(v is None for v in case["human_fields"].values()))
            self.assertEqual([e["text"] for e in case["retained_evidence"]],
                             [e["text"] for e in original["writer_retained_evidence"]])
            for e in case["retained_evidence"]:
                self.assertLessEqual(set(e), set(bundle.EVIDENCE_FIELDS))
                self.assertNotIn("fusion_score", e)
                self.assertNotIn("selection_reason", e)
        self.assertEqual(sum(c["frozen_gold"]["no_answer"] for c in self.cases), 12)
        blank_gold = [c for c in self.cases if c["query_id"] == "dev-secret-pov"]
        self.assertEqual(len(blank_gold), 3)
        self.assertTrue(all(c["frozen_gold"]["expected_answer"] == "" for c in blank_gold))

    def test_reviewer_private_sources_are_separate_from_retained_sources(self):
        private = [c for c in self.cases if c["query_id"] == "q19"]
        author = [c for c in self.cases if c["query_id"] == "q20"]
        self.assertEqual(len(private), 3)
        for c in private:
            self.assertIn("h22", [r["source_id"] for r in c["supporting_source_passages"]])
            self.assertNotIn("h22", [e["source_id"] for e in c["retained_evidence"]])
        for c in author:
            self.assertIn("h22", [e["source_id"] for e in c["retained_evidence"]])

    def test_zip_integrity_unchanged_corpora_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "review"
            with contextlib.redirect_stdout(io.StringIO()):
                bundle.build(AUDIT, FIXTURES, REPLAY, out)
            manifest = bundle.load(out / "manifest.json")
            with zipfile.ZipFile(out.with_suffix(".zip")) as z:
                self.assertIsNone(z.testzip())
                self.assertEqual(len(z.namelist()), len(manifest["files"]) + 1)
                for name, sha in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(z.read("review/" + name)).hexdigest(), sha)
                    self.assertNotIn("blind-key", name)
                    self.assertNotIn("adjudication", name)
            for name, raw in self.corpora.items():
                self.assertEqual((out / name).read_bytes(), raw)
            scores = bundle.load(out / "human-scores.json")
            self.assertIsNone(scores["reviewer_kind"])
            with self.assertRaises(AssertionError):
                bundle.build(AUDIT, FIXTURES, REPLAY, out)


if __name__ == "__main__":
    unittest.main()
