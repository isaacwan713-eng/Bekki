import json
from pathlib import Path
import unittest

import knowledge_evidence


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class KnowledgeEvidenceIndexBootstrapHotfixTests(unittest.TestCase):
    def test_reported_24_legacy_claims_are_valid_before_index_bootstrap(self):
        legacy = [
            {
                "id": "knowledge_legacy_" + str(index),
                "subject": "Legacy",
                "claim": "Legacy claim " + str(index),
                "status": "verified",
            }
            for index in range(24)
        ]
        audit = knowledge_evidence.audit_evidence_store(
            legacy,
            media_index={"schema_version": 1, "assets": {}},
            verify_files=False,
        )
        self.assertEqual(audit["counts"]["claims"], 24)
        self.assertEqual(audit["counts"]["legacy_compatible"], 24)
        self.assertEqual(audit["failures"], [])
        self.assertFalse(
            knowledge_evidence.media_index_document_required(audit)
        )

    def test_text_only_store_does_not_require_media_index(self):
        counts = {
            "claims": 1,
            "contract_current": 1,
            "legacy_compatible": 0,
            "text_claims": 1,
            "image_claims": 0,
            "media_assets": 0,
            "referenced_assets": 0,
        }
        self.assertFalse(
            knowledge_evidence.media_index_document_required({
                "counts": counts,
                "failures": [],
            })
        )

    def test_any_image_lineage_requires_authoritative_media_index(self):
        for field in ("image_claims", "referenced_assets", "media_assets"):
            counts = {
                "image_claims": 0,
                "referenced_assets": 0,
                "media_assets": 0,
            }
            counts[field] = 1
            with self.subTest(field=field):
                self.assertTrue(
                    knowledge_evidence.media_index_document_required(
                        {"counts": counts, "failures": []}
                    )
                )

    def test_malformed_media_accounting_fails_closed(self):
        self.assertTrue(
            knowledge_evidence.media_index_document_required({
                "counts": {"image_claims": "invalid"}
            })
        )

    def test_validator_keeps_sqlite_read_only_and_uses_conditional_rule(self):
        validator = (
            ROOT / "TEST_KNOWLEDGE_EVIDENCE_LINEAGE_V1_10_54_5.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn("?mode=ro", validator)
        self.assertIn("PRAGMA query_only=ON", validator)
        self.assertIn("media_index_document_required", validator)
        self.assertIn("media_index_state_valid", validator)
        self.assertNotIn("not media_index_document_present,", validator)

    def test_build_metadata_and_hotfix_entrypoint(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Autonomous Visual Evidence V1.10.54.6",
        )
        wrapper = (
            ROOT
            / "TEST_KNOWLEDGE_EVIDENCE_INDEX_BOOTSTRAP_HOTFIX_V1_10_54_5_1.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "TEST_KNOWLEDGE_EVIDENCE_LINEAGE_V1_10_54_5.ps1",
            wrapper,
        )
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
