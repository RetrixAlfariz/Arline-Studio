from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STREAM_JS = ROOT / "src/interface/web/static/js/stream.js"
SHEETS_JS = ROOT / "src/interface/web/static/js/discovery-sheets.js"
DISCOVERY_WEB = ROOT / "src/discovery/web.py"
PROVISIONAL = ROOT / "src/discovery/provisional.py"
PROVISIONAL_RUNTIME = ROOT / "src/discovery/provisional_runtime.py"
SPATIAL = ROOT / "src/discovery/spatial.py"


class V121ProvisionalSheetUITests(unittest.TestCase):
    def test_runtime_loads_provisional_sheet_enhancement(self):
        stream = STREAM_JS.read_text(encoding="utf-8")
        sheet = SHEETS_JS.read_text(encoding="utf-8")
        self.assertIn("/static/js/discovery-sheets.js?v=1.2.1-provisional", stream)
        self.assertIn("data-arline-provisional-sheets", stream)
        self.assertIn('document.readyState === "loading"', sheet)
        self.assertIn("ArlineProvisionalSheets", sheet)

    def test_sheet_explains_stable_identity_and_per_claim_provenance(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        self.assertIn("sheet ID is stable and callable with @", source)
        self.assertIn("Each value/relation keeps its own proposition ID", source)
        self.assertIn("claim.id", source)
        self.assertIn("change.from_proposition_id", source)
        self.assertIn("change.to_proposition_id", source)

    def test_user_can_choose_correction_story_change_or_canon(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        api = DISCOVERY_WEB.read_text(encoding="utf-8")
        self.assertIn('data-prov-action="correct"', source)
        self.assertIn('data-prov-action="story"', source)
        self.assertIn('data-prov-action="canon"', source)
        self.assertIn('mode === "story_change"', source)
        self.assertIn('@router.post("/discoveries/{proposition_id}/edit")', api)
        self.assertIn('mode: str = "correction"', api)

    def test_relations_are_first_class_non_canon_sheet_data(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        provisional = PROVISIONAL.read_text(encoding="utf-8")
        self.assertIn("Relations", source)
        self.assertIn("source-backed provisional relation", source)
        self.assertIn("data-prov-relation", source)
        self.assertIn('prop.get("operation") == "relation"', provisional)
        self.assertIn("SPATIAL_RELATIONS", provisional)

    def test_lightweight_zone_edge_cannot_be_promoted_as_fake_entity(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        runtime = PROVISIONAL_RUNTIME.read_text(encoding="utf-8")
        self.assertIn('rel.object_type === "spatial_zone"', source)
        self.assertIn("Lightweight spatial-zone edge", source)
        self.assertIn('prop.get("object_type") == "spatial_zone"', runtime)
        self.assertIn("not directly canonizable", runtime)

    def test_provisional_sheet_visibility_uses_source_branch_lineage(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        runtime = PROVISIONAL_RUNTIME.read_text(encoding="utf-8")
        self.assertIn("function provisionalVisible", source)
        self.assertIn("activeBranchLineageIds", source)
        self.assertIn("source_branch_ids", source)
        self.assertIn("parent_branch_id", source)
        self.assertIn("filteredWorldFamilies", source)
        self.assertIn("referenceRegistry", source)
        self.assertIn("another branch lineage", source)
        self.assertIn('meta["source_branch_ids"]', runtime)
        self.assertIn("_source_branch_ids", runtime)

    def test_apartment_is_a_type_floor_is_zone_and_unit_is_sheet(self):
        source = SPATIAL.read_text(encoding="utf-8")
        self.assertIn('"location_kind": "apartment_building"', source)
        self.assertIn('"zone_kind": "floor"', source)
        self.assertIn('"location_kind": "apartment_unit"', source)
        self.assertIn('"floor_number"', source)
        self.assertIn('"area_m2"', source)
        self.assertIn('"room_count"', source)
        self.assertNotIn('subject_label="Apartemen"', source)


if __name__ == "__main__":
    unittest.main()
