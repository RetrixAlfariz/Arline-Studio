from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "src/interface/web/static/index.html"
SHEETS_JS = ROOT / "src/interface/web/static/js/discovery-sheets.js"
DISCOVERY_WEB = ROOT / "src/discovery/web.py"
PROVISIONAL = ROOT / "src/discovery/provisional.py"
PROVISIONAL_RUNTIME = ROOT / "src/discovery/provisional_runtime.py"
PROMOTION = ROOT / "src/discovery/promotion.py"
SEMANTICS = ROOT / "src/discovery/semantics.py"
SPATIAL = ROOT / "src/discovery/spatial.py"
SPATIAL_V2 = ROOT / "src/discovery/spatial_v2.py"
GARMENT = ROOT / "src/discovery/garment.py"
PHYSICAL_ITEMS = ROOT / "src/discovery/physical_items.py"


class V121ProvisionalSheetUITests(unittest.TestCase):
    def test_runtime_loads_provisional_sheet_enhancement(self):
        html = INDEX_HTML.read_text(encoding="utf-8")
        sheet = SHEETS_JS.read_text(encoding="utf-8")
        self.assertIn("/static/js/discovery-sheets.js?v=1.2.4-directives", html)
        self.assertNotIn("data-arline-provisional-sheets", html)
        self.assertIn('document.readyState === "loading"', sheet)
        self.assertIn("ArlineProvisionalSheets", sheet)

    def test_sheet_explains_stable_identity_and_per_claim_provenance(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        self.assertIn("sheet ID is stable and callable with @", source)
        self.assertIn("Each value/relation keeps its own proposition ID", source)
        self.assertIn("claim.id", source)
        self.assertIn("change.from_proposition_id", source)
        self.assertIn("change.to_proposition_id", source)

    def test_physical_item_identity_is_visible_and_separate_from_garment_type(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        garment = GARMENT.read_text(encoding="utf-8")
        physical = PHYSICAL_ITEMS.read_text(encoding="utf-8")
        self.assertIn("function physicalIdentity", source)
        self.assertIn("physical_item_id", source)
        self.assertIn("Item › Garment ›", source)
        self.assertIn("relationPhysicalId", source)
        self.assertIn("Physical ITEM identity is stable", source)
        self.assertIn('"identity_model": "physical_instance_v1"', garment)
        self.assertIn('return f"ITEM-{digest}"', physical)
        self.assertIn('return f"item:{item_id}"', physical)

    def test_user_can_choose_correction_story_change_or_canon(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        api = DISCOVERY_WEB.read_text(encoding="utf-8")
        self.assertIn('data-prov-action="correct"', source)
        self.assertIn('data-prov-action="story"', source)
        self.assertIn('data-prov-action="canon"', source)
        self.assertIn('mode === "story_change"', source)
        self.assertIn('@router.post("/discoveries/{proposition_id}/edit")', api)
        self.assertIn('mode: str = "correction"', api)

    def test_typed_semantics_and_projection_are_visible_in_sheet(self):
        source = SHEETS_JS.read_text(encoding="utf-8")
        semantics = SEMANTICS.read_text(encoding="utf-8")
        promotion = PROMOTION.read_text(encoding="utf-8")
        self.assertIn("function semanticText", source)
        self.assertIn("canon_target", source)
        self.assertIn("claim?.semantics?.canonizable", source)
        self.assertIn("result?.projection?.status", source)
        self.assertIn("Canon saved · projected to", source)
        self.assertIn('"projection": "variant.current_state"', semantics)
        self.assertIn('"canon_target": "timeline_or_fact"', semantics)
        self.assertIn("_project_canon", promotion)

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
        promotion = PROMOTION.read_text(encoding="utf-8")
        semantics = SEMANTICS.read_text(encoding="utf-8")
        self.assertIn("relation?.semantics?.canonizable === false", source)
        self.assertIn("Lightweight spatial-zone edge", source)
        self.assertIn('prop.get("object_type") == "spatial_zone"', runtime)
        self.assertIn("Lightweight spatial-zone edges cannot become canonical", promotion)
        self.assertIn('lightweight = object_type == "spatial_zone"', semantics)

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

    def test_generic_spatial_grammar_stays_precision_first(self):
        source = SPATIAL_V2.read_text(encoding="utf-8")
        self.assertIn('"gedung": "building"', source)
        self.assertIn('"asrama": "dormitory"', source)
        self.assertIn('"ruang": "room"', source)
        self.assertIn('"zone_kind": "floor"', source)
        self.assertIn("detect_generic_location_hierarchy", source)
        self.assertIn("result = legacy(text)", source)


if __name__ == "__main__":
    unittest.main()
