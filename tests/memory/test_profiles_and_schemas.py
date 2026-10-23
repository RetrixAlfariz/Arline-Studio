from __future__ import annotations

import unittest

from pydantic import ValidationError

from src.memory.contracts import schema_document, validate_structured_output
from src.memory.profiles import TASK_PROFILES


class V120ProfileContractTests(unittest.TestCase):
    def test_all_task_profiles_are_isolated_and_cannot_commit_canon(self) -> None:
        required = {
            "story_writer", "dialogue_writer", "structure_extractor",
            "memory_summarizer", "evidence_analyst", "continuity_explainer",
            "branch_comparison", "ambiguous_query_router",
        }
        self.assertEqual(set(TASK_PROFILES), required)
        for profile in TASK_PROFILES.values():
            self.assertFalse(profile.may_commit_canon, profile.id)
            self.assertFalse(profile.inherit_hidden_history, profile.id)
            self.assertTrue(profile.system_contract.strip(), profile.id)
            self.assertTrue(profile.context_recipe_id.strip(), profile.id)

    def test_extractor_and_summary_profiles_bind_official_schemas(self) -> None:
        self.assertEqual(TASK_PROFILES["structure_extractor"].output_schema_id, "memory_proposals_v1")
        self.assertEqual(TASK_PROFILES["memory_summarizer"].output_schema_id, "memory_summary_v1")
        self.assertIn("properties", schema_document("memory_proposals_v1"))
        self.assertIn("properties", schema_document("memory_summary_v1"))

    def test_empty_extraction_is_valid_but_claim_without_evidence_is_not(self) -> None:
        empty = validate_structured_output("memory_proposals_v1", {})
        self.assertEqual(empty["events"], [])
        self.assertEqual(empty["state_changes"], [])

        with self.assertRaises(ValidationError):
            validate_structured_output("memory_proposals_v1", {
                "events": [{
                    "event_type": "departure",
                    "summary": "Fano left.",
                    "evidence": [],
                }]
            })

    def test_summary_requires_source_evidence_and_separates_inference(self) -> None:
        valid = validate_structured_output("memory_summary_v1", {
            "summary_type": "scene",
            "subject_type": "document",
            "subject_id": "SCENE-1",
            "text": "Vian returned home.",
            "explicit_facts": ["Vian returned home."],
            "inferences": ["Vian may be tired."],
            "uncertainties": ["Reason for returning is unstated."],
            "source_chunk_ids": ["CHUNK-1"],
        })
        self.assertEqual(valid["source_chunk_ids"], ["CHUNK-1"])
        self.assertNotEqual(valid["explicit_facts"], valid["inferences"])

        with self.assertRaises(ValidationError):
            validate_structured_output("memory_summary_v1", {
                "summary_type": "scene",
                "subject_type": "document",
                "subject_id": "SCENE-1",
                "text": "Unsupported summary.",
                "source_chunk_ids": [],
            })


if __name__ == "__main__":
    unittest.main()
