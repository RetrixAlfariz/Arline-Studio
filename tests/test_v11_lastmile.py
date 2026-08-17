from __future__ import annotations
from pathlib import Path
import tempfile
import unittest

from src.workspace import WorkspaceStore, WORLD_BIBLE_WORLD_ID

ROOT=Path(__file__).resolve().parents[1]

class V11LastMileTests(unittest.TestCase):
    def test_safe_identity_merge_moves_non_overlapping_variants(self):
        with tempfile.TemporaryDirectory() as td:
            store=WorkspaceStore(Path(td)/"db.sqlite")
            target=store.create_entity_family(None,"Apartment",entity_type="location")
            source=store.create_entity_family(None,"A0325",entity_type="location",create_variant_in_world=WORLD_BIBLE_WORLD_ID)
            preview=store.preview_entity_family_merge(source["id"],target["id"])
            self.assertTrue(preview["safe"])
            merged=store.merge_entity_families(source["id"],target["id"])
            self.assertEqual(len(merged["variants"]),1)
            with self.assertRaises(KeyError): store.get_entity_family(source["id"])

    def test_identity_merge_blocks_scope_collision(self):
        with tempfile.TemporaryDirectory() as td:
            store=WorkspaceStore(Path(td)/"db.sqlite")
            left=store.create_entity_family(None,"Left",entity_type="character",create_variant_in_world=WORLD_BIBLE_WORLD_ID)
            right=store.create_entity_family(None,"Right",entity_type="character",create_variant_in_world=WORLD_BIBLE_WORLD_ID)
            preview=store.preview_entity_family_merge(left["id"],right["id"])
            self.assertFalse(preview["safe"])
            with self.assertRaises(ValueError): store.merge_entity_families(left["id"],right["id"])

    def test_last_mile_ui_foundations_exist(self):
        js=(ROOT/"src/interface/web/static/arline.js").read_text(encoding="utf-8")
        html=(ROOT/"src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn("composerDraftKey",js)
        self.assertIn("turnForks",js)
        self.assertIn("openEntityMergeForm",js)
        self.assertIn("bulkMoveSelected",js)
        self.assertIn('id="worldBulkBar"',html)

if __name__=="__main__": unittest.main()
