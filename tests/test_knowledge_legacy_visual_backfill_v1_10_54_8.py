from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import knowledge_evidence
import knowledge_visual_backfill
import knowledge_worker


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"
PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "/x8AAusB9Y9Z4QAAAABJRU5ErkJggg=="
)
PAGE_TEXT = "官方资料写明：四禧丸子的角色造型融入国风元素。"


def public_source(number=1):
    return {
        "title": "四禧丸子官方介绍 " + str(number),
        "name": "四禧丸子官方介绍 " + str(number),
        "url": "https://official.example/characters/" + str(number),
        "domain": "official.example",
        "source_score": 96,
    }


def legacy_item(number=1):
    return {
        "id": "knowledge_legacy_visual_" + str(number),
        "subject": "四禧丸子",
        "claim": "四禧丸子的角色造型融入国风元素。",
        "topics": ["四禧丸子"],
        "knowledge_type": "stable",
        "expires_at": None,
        "status": "verified",
        "verification_status": "DOUBLE_CERTIFIED_MULTI_SOURCE",
        "confidence": 0.96,
        "sources": [public_source(number)],
        "temporal_scope": {},
        "learned_at": "2026-01-0" + str(number) + "T00:00:00+00:00",
        "lifecycle_version": knowledge.KNOWLEDGE_LIFECYCLE_VERSION,
    }


class KnowledgeLegacyVisualBackfillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.data_dir = Path(self.temporary.name) / "data"
        patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(self.data_dir),
            KNOWLEDGE_FILE=str(self.data_dir / "knowledge.json"),
            SOURCES_FILE=str(self.data_dir / "knowledge_sources.json"),
            LOGS_FILE=str(self.data_dir / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(
                self.data_dir / "knowledge_source_candidates.json"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    def _save(self, items):
        knowledge._save_knowledge(items, sync_curation=False)

    @staticmethod
    def _reader(source, *, include_images=False):
        if include_images:
            source["_page_images"] = [PNG_BASE64]
            source["_page_image_labels"] = ["官方国风角色画面"]
            source["_page_image_urls"] = [
                "https://cdn.example/character.png?token=discarded"
            ]
        return PAGE_TEXT

    @staticmethod
    def _proposal(item):
        return {
            "decision": "ATTACH",
            "knowledge_id": item["id"],
            "claim_fingerprint": (
                knowledge.visual_backfill_claim_fingerprint(item)
            ),
            "evidence_excerpt": "四禧丸子的角色造型融入国风元素",
            "image_indexes": [1],
            "visual_observation": "官方画面显示带有国风服饰元素的角色造型。",
            "reason": "The text and image both support the fixed claim.",
        }

    def _approving_ai(self, item, calls):
        proposal = self._proposal(item)
        normalized = knowledge_visual_backfill._normalized_proposal(
            proposal,
            item["id"],
            knowledge.visual_backfill_claim_fingerprint(item),
            1,
        )
        proposal_hash = knowledge_visual_backfill.proposal_fingerprint(
            normalized
        )

        def answer(prompt_path, prompt_text, **kwargs):
            calls.append((prompt_path, prompt_text, kwargs))
            if prompt_path.endswith("_verify.txt"):
                return {
                    "decision": "APPROVE",
                    "knowledge_id": item["id"],
                    "claim_fingerprint": (
                        knowledge.visual_backfill_claim_fingerprint(item)
                    ),
                    "proposal_fingerprint": proposal_hash,
                    "reason": "Independent visual review passed.",
                }
            return deepcopy(proposal)

        return answer

    def test_only_active_verified_image_free_claims_with_bound_https_sources(self):
        good = legacy_item(1)
        private = legacy_item(2)
        private["sources"][0].update({
            "user_supplied": True,
            "privacy_class": "PRIVATE_MEDIA",
        })
        disputed = legacy_item(3)
        disputed["status"] = "disputed"
        expired = legacy_item(4)
        expired.update({
            "knowledge_type": "reviewable",
            "expires_at": "2020-01-01T00:00:00+00:00",
        })
        with_image = legacy_item(5)
        with_image["evidence_bundle"] = {
            "records": [{"modality": "IMAGE"}],
        }
        local_network = legacy_item(6)
        local_network["sources"][0]["url"] = "https://127.0.0.1/private"
        self._save([
            good,
            private,
            disputed,
            expired,
            with_image,
            local_network,
        ])

        selected = knowledge_visual_backfill.eligible_candidates()
        self.assertEqual(
            [value["item"]["id"] for value in selected],
            [good["id"]],
        )

    def test_no_images_uses_no_model_and_records_retry_without_claim_mutation(self):
        item = legacy_item()
        self._save([item])
        before = deepcopy(knowledge.load_items())

        def reader(_source, *, include_images=False):
            self.assertTrue(include_images)
            return PAGE_TEXT

        with patch("knowledge_visual_backfill.tools.run_ai_prompt") as model:
            result = knowledge_visual_backfill.run_once(reader=reader)

        self.assertEqual(result["status"], "NO_ATTACHMENT")
        self.assertEqual(result["claims_attempted"], 1)
        self.assertEqual(result["proposal_calls"], 0)
        model.assert_not_called()
        self.assertEqual(knowledge.load_items(), before)
        self.assertEqual(
            knowledge_visual_backfill.eligible_candidates(), []
        )
        state = knowledge_visual_backfill.load_state()
        attempt = next(iter(state["attempts"].values()))
        self.assertEqual(attempt["status"], "NO_IMAGES")
        self.assertIsNotNone(attempt["next_attempt_at"])

    def test_dual_ai_approval_attaches_sealed_evidence_without_rewriting_claim(self):
        item = legacy_item()
        item["sources"][0]["url"] += "?access_token=legacy-secret#profile"
        self._save([item])
        before = deepcopy(knowledge.load_items()[0])
        calls = []

        reader_urls = []

        def reader(source, *, include_images=False):
            reader_urls.append(source["url"])
            return self._reader(source, include_images=include_images)

        result = knowledge_visual_backfill.run_once(
            reader=reader,
            ai_prompt=self._approving_ai(item, calls),
        )

        self.assertEqual(result["status"], "ATTACHED")
        self.assertEqual(result["claims_attached"], 1)
        self.assertEqual(result["proposal_calls"], 1)
        self.assertEqual(result["verification_calls"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            reader_urls,
            ["https://official.example/characters/1"],
        )
        for _path, prompt_text, kwargs in calls:
            self.assertNotIn(PNG_BASE64, prompt_text)
            self.assertNotIn("legacy-secret", prompt_text)
            self.assertIn("images", kwargs)
        saved = knowledge.load_items()[0]
        for field in (
            "id", "subject", "claim", "topics", "knowledge_type",
            "expires_at", "status", "verification_status", "sources",
            "temporal_scope", "confidence", "learned_at",
        ):
            self.assertEqual(saved.get(field), before.get(field), field)
        self.assertEqual(
            saved["visual_evidence_backfill"]["status"], "ATTACHED"
        )
        self.assertEqual(
            set(saved["evidence_bundle"]["modalities"]),
            {"TEXT", "IMAGE"},
        )
        audit = knowledge.audit_knowledge_evidence()
        self.assertEqual(audit["failures"], [])
        self.assertEqual(audit["counts"]["image_claims"], 1)
        self.assertEqual(
            knowledge_visual_backfill.audit_state()["failures"], []
        )
        serialized = json.dumps(
            {
                "claim": saved,
                "state": knowledge_visual_backfill.load_state(),
                "result": result,
            },
            ensure_ascii=False,
        )
        self.assertNotIn(PNG_BASE64, serialized)
        self.assertNotIn(str(self.data_dir), serialized)
        media_index = knowledge_evidence.load_media_index(str(self.data_dir))
        asset = next(iter(media_index["assets"].values()))
        self.assertNotIn("token=", json.dumps(asset))
        new_artifacts = json.dumps(
            {
                "evidence_bundle": saved["evidence_bundle"],
                "state": knowledge_visual_backfill.load_state(),
                "result": result,
                "media_index": media_index,
            },
            ensure_ascii=False,
        )
        self.assertNotIn("legacy-secret", new_artifacts)

    def test_proposal_binding_mismatch_fails_before_independent_verifier(self):
        item = legacy_item()
        self._save([item])
        proposal = self._proposal(item)
        proposal["knowledge_id"] = "knowledge_wrong"
        calls = []

        def ai(prompt_path, _prompt_text, **_kwargs):
            calls.append(prompt_path)
            return proposal

        result = knowledge_visual_backfill.run_once(
            reader=self._reader,
            ai_prompt=ai,
        )
        self.assertEqual(result["claims_attached"], 0)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("evidence_bundle", knowledge.load_items()[0])

    def test_independent_verifier_rejection_preserves_legacy_claim(self):
        item = legacy_item()
        self._save([item])
        proposal = self._proposal(item)
        normalized = knowledge_visual_backfill._normalized_proposal(
            proposal,
            item["id"],
            knowledge.visual_backfill_claim_fingerprint(item),
            1,
        )
        proposal_hash = knowledge_visual_backfill.proposal_fingerprint(
            normalized
        )

        def ai(prompt_path, _prompt_text, **_kwargs):
            if prompt_path.endswith("_verify.txt"):
                return {
                    "decision": "REJECT",
                    "knowledge_id": item["id"],
                    "claim_fingerprint": (
                        knowledge.visual_backfill_claim_fingerprint(item)
                    ),
                    "proposal_fingerprint": proposal_hash,
                    "reason": "The image is too generic.",
                }
            return proposal

        result = knowledge_visual_backfill.run_once(
            reader=self._reader,
            ai_prompt=ai,
        )
        self.assertEqual(result["status"], "NO_ATTACHMENT")
        self.assertEqual(result["claims_attached"], 0)
        self.assertEqual(result["verification_calls"], 1)
        self.assertNotIn("evidence_bundle", knowledge.load_items()[0])

    def test_attach_api_rejects_changed_claim_or_unbound_source(self):
        item = legacy_item()
        self._save([item])
        other = public_source(2)
        seed = knowledge_evidence.autonomous_evidence_seed(
            other,
            PAGE_TEXT,
            {
                "claim": item["claim"],
                "evidence_excerpt": "四禧丸子的角色造型融入国风元素",
                "evidence": {
                    "modality": "TEXT_AND_IMAGE",
                    "image_indexes": [1],
                    "visual_observation": "画面显示国风服饰元素。",
                },
            },
            [PNG_BASE64],
            ["官方画面"],
            ["https://cdn.example/other.png"],
        )
        other_source_id = knowledge_evidence.compact_source(other)["source_id"]
        status, _item = knowledge.attach_visual_evidence_to_existing_claim(
            item["id"],
            "0" * 64,
            other_source_id,
            seed,
        )
        self.assertEqual(status, "claim_changed")
        status, _item = knowledge.attach_visual_evidence_to_existing_claim(
            item["id"],
            knowledge.visual_backfill_claim_fingerprint(item),
            other_source_id,
            seed,
        )
        self.assertEqual(status, "source_not_bound")
        self.assertEqual(
            knowledge_evidence.load_media_index(str(self.data_dir))["assets"],
            {},
        )

    def test_one_cycle_is_bounded_to_one_claim(self):
        first = legacy_item(1)
        second = legacy_item(2)
        self._save([first, second])
        calls = []
        result = knowledge_visual_backfill.run_once(
            reader=self._reader,
            ai_prompt=self._approving_ai(first, calls),
            limit=99,
        )
        self.assertEqual(result["claims_attempted"], 1)
        self.assertEqual(result["claims_attached"], 1)
        saved = {value["id"]: value for value in knowledge.load_items()}
        self.assertIn("evidence_bundle", saved[first["id"]])
        self.assertNotIn("evidence_bundle", saved[second["id"]])

    def test_learning_cycle_accounting_includes_enabled_backfill(self):
        backfill = knowledge_visual_backfill._empty_result()
        backfill.update({
            "status": "ATTACHED",
            "eligible_claims": 1,
            "claims_attempted": 1,
            "claims_attached": 1,
            "attached_knowledge_ids": ["knowledge_legacy_visual_1"],
        })
        empty_reviews = {
            "approved": 0,
            "pending": 0,
            "rejected": 0,
            "errors": 0,
        }
        with (
            patch.object(knowledge_worker, "choose_sources", return_value=[]),
            patch.object(
                knowledge_worker,
                "discover_source_candidates",
                return_value=0,
            ),
            patch.object(
                knowledge_worker,
                "review_source_candidates",
                return_value=empty_reviews,
            ),
            patch.object(
                knowledge_worker.knowledge_visual_backfill,
                "run_once",
                return_value=backfill,
            ) as runner,
            patch.object(
                knowledge_worker,
                "organize_learned_knowledge",
                return_value={"status": "SKIPPED"},
            ),
        ):
            log = knowledge_worker.run_learning_cycle(
                topics=["四禧丸子"],
                trigger="unit_test",
                enable_legacy_visual_backfill=True,
            )
        runner.assert_called_once_with(reader=knowledge_worker.read_source)
        self.assertEqual(log["status"], "COMPLETED")
        self.assertEqual(log["verified_evidence_count"], 1)
        self.assertEqual(
            log["legacy_visual_backfill"]["claims_attached"], 1
        )
        self.assertEqual(
            log["knowledge_legacy_visual_backfill_contract_version"], 1
        )


class KnowledgeLegacyVisualBackfillBuildTests(unittest.TestCase):
    def test_build_metadata_release_files_and_mirrors(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Legacy Visual Evidence Backfill V1.10.54.8",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata[
                "knowledge_legacy_visual_backfill_contract_version"
            ],
            1,
        )
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))
        for relative in (
            "README.md",
            "INSTALL.txt",
            "KNOWLEDGE_LEGACY_VISUAL_BACKFILL_V1_10_54_8_NOTES.md",
            "TEST_KNOWLEDGE_LEGACY_VISUAL_BACKFILL_V1_10_54_8.ps1",
        ):
            self.assertIn(
                "V1.10.54.8",
                (ROOT / relative).read_text(encoding="utf-8"),
                relative,
            )
        for relative in (
            "knowledge.py",
            "knowledge_evidence.py",
            "knowledge_visual_backfill.py",
            "knowledge_worker.py",
            "prompts/knowledge_legacy_visual_backfill.txt",
            "prompts/knowledge_legacy_visual_backfill_verify.txt",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
                relative,
            )


if __name__ == "__main__":
    unittest.main()
