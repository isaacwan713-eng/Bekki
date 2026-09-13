import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import knowledge
import knowledge_worker
from nerv import knowledge_curator
from nerv.knowledge_curator import KnowledgeCurator


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


def item(item_id, subject, claim, topics=None, **updates):
    value = {
        "id": item_id,
        "subject": subject,
        "claim": claim,
        "topics": list(topics or [subject]),
        "knowledge_domain": "culture_entertainment",
        "cluster_label": subject,
        "learned_at": datetime.now(timezone.utc).isoformat(),
        "confidence": 0.95,
        "knowledge_type": "stable",
        "valid_for_days": None,
        "expires_at": None,
        "risk": "low",
        "status": "verified",
        "verification_status": "AI_PLUS_SOURCE_CORROBORATION",
        "sources": [],
        "provenance": {"origin": "knowledge_worker"},
    }
    value.update(updates)
    return value


def assignment(
    current,
    topic_id,
    topic_title,
    subject_id=None,
    subject_name=None,
):
    subject_name = subject_name or current["subject"]
    subject_id = subject_id or topic_id
    return {
        "knowledge_id": current["id"],
        "decision": "STORE",
        "topic_id": topic_id,
        "topic_title": topic_title,
        "topic_aliases": [subject_name],
        "topic_keywords": [subject_name],
        "subject_entity": {
            "id": subject_id,
            "name": subject_name,
            "type": "organization",
            "aliases": [],
        },
        "literal_claim_subject": current["subject"],
        "selected_subject_entity_id": subject_id,
        "rejected_adjacent_entity_ids": [],
        "subject_selection_reason": (
            "The exact verified subject is selected."
        ),
        "related_entities": [],
        "facet": "organization_background",
        "claim_keywords": [subject_name],
        "preferred_display_claim": current["claim"],
        "preferred_display_language": "source",
        "name_rendering_status": "SOURCE_PRESERVED",
        "display_semantics_preserved": True,
        "related_claim_ids": [],
        "entity_scope_preserved": True,
        "relationship_semantics_consistent": True,
        "reason": "Store this verified claim in its matching ecosystem.",
    }


def topic(topic_id, title, aliases=None, entities=None, claims=None):
    return {
        "topic_id": topic_id,
        "title": title,
        "aliases": list(aliases or [title]),
        "keywords": list(aliases or [title]),
        "entities": list(entities or []),
        "relationships": [],
        "classification": {},
        "lifecycle": {},
        "claims": list(claims or []),
    }


class CuratorIsolationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        data = Path(self.temporary.name) / "data"
        patcher = patch.multiple(
            knowledge,
            DATA_DIR=str(data),
            KNOWLEDGE_FILE=str(data / "knowledge.json"),
            SOURCES_FILE=str(data / "knowledge_sources.json"),
            LOGS_FILE=str(data / "learning_logs.json"),
            PENDING_SOURCES_FILE=str(data / "knowledge_source_candidates.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        knowledge.initialize()

    @staticmethod
    def _akb_item(item_id="knowledge_akb_definition", claim=None):
        return item(
            item_id,
            "AKB48",
            claim or "AKB48 is a Japanese idol group based in Akihabara.",
            ["AKB48", "Japanese idol"],
        )

    @staticmethod
    def _akb_topic():
        return topic(
            "akb48_ecosystem",
            "AKB48",
            ["AKB48"],
            entities=[{
                "id": "akb48",
                "name": "AKB48",
                "type": "idol_group",
                "aliases": [],
            }],
            claims=[{
                "id": "knowledge_akb_seed",
                "subject": "AKB48",
                "claim": "AKB48 operates a theater in Akihabara.",
                "subject_entity_id": "akb48",
                "facet": "theater",
                "knowledge_layer": "L1_FOUNDATION",
                "fact_type": "ATTRIBUTE",
                "temporal_scope": {},
            }],
        )

    @staticmethod
    def _four_xi_topic():
        return topic(
            "sihixian_ecosystem",
            "四禧丸子",
            ["四禧丸子", "Sihixian"],
            entities=[{
                "id": "sihixian_maruko",
                "name": "四禧丸子",
                "type": "virtual_idol_group",
                "aliases": ["Sihixian"],
            }],
            claims=[{
                "id": "knowledge_sihixian_seed",
                "subject": "四禧丸子",
                "claim": "四禧丸子是虚拟偶像团体。",
                "subject_entity_id": "sihixian_maruko",
                "facet": "identity",
                "knowledge_layer": "L1_FOUNDATION",
                "fact_type": "IDENTITY_DEFINITION",
                "temporal_scope": {},
            }],
        )

    def test_relevant_catalog_excludes_cross_topic_distractor(self):
        current = self._akb_item()
        compact = {
            **current,
            "knowledge_id": current["id"],
            "display_context": {},
        }
        selected = KnowledgeCurator._relevant_catalog(
            compact,
            [self._four_xi_topic(), self._akb_topic()],
        )
        self.assertEqual(
            [value["topic_id"] for value in selected],
            ["akb48_ecosystem"],
        )
        self.assertNotIn("四禧丸子", json.dumps(selected, ensure_ascii=False))

    def test_primary_packet_is_bounded_and_exactly_fingerprinted(self):
        current = self._akb_item()
        current["verification"] = {
            "accepted_answer": "accepted-context-" * 4000,
            "evidence_answers": ["evidence-context-" * 4000] * 10,
        }
        current["provenance"]["large_internal_blob"] = "private-noise-" * 10000
        fingerprint = knowledge._curation_fingerprint(current)
        entry = {
            "knowledge_id": current["id"],
            "fingerprint": fingerprint,
        }
        catalogs = [self._akb_topic()] + [
            topic(
                "unrelated_" + str(index),
                "四禧丸子噪声" + str(index),
                ["四禧丸子", "virtual idol"],
                claims=[{
                    "id": "unrelated_claim_" + str(index),
                    "subject": "四禧丸子",
                    "claim": "unrelated-secret-" * 2000,
                }],
            )
            for index in range(80)
        ]
        calls = []

        def model_call(prompt_path, payload, **kwargs):
            packet = json.loads(payload)
            calls.append((prompt_path, packet, payload, kwargs))
            return {
                "curation_fingerprint": packet[
                    "required_curation_fingerprint"
                ],
                "assignments": [assignment(
                    current,
                    "akb48_ecosystem",
                    "AKB48",
                    subject_id="akb48",
                )],
                "reason": "The matching AKB48 ecosystem is supplied.",
            }

        with (
            patch.object(knowledge, "load_items", return_value=[current]),
            patch.object(knowledge, "load_topic_catalog", return_value=catalogs),
        ):
            result = KnowledgeCurator(model_call)._plan_batch([entry])

        self.assertEqual(result[0]["knowledge_id"], current["id"])
        self.assertEqual(len(calls), 1)
        prompt_path, packet, payload, options = calls[0]
        self.assertEqual(prompt_path, "prompts/nerv_daily_knowledge_curator.txt")
        self.assertLessEqual(
            len(payload.encode("utf-8")),
            knowledge_curator.MAX_CURATOR_PACKET_BYTES,
        )
        self.assertEqual(packet["current_knowledge_id"], current["id"])
        self.assertEqual(
            packet["required_curation_fingerprint"],
            fingerprint,
        )
        self.assertEqual(
            [value["topic_id"] for value in packet["relevant_topic_ecosystems"]],
            ["akb48_ecosystem"],
        )
        self.assertNotIn("unrelated-secret", payload)
        self.assertNotIn("private-noise", payload)
        self.assertEqual(options["num_ctx"], 8192)
        self.assertEqual(options["num_predict"], 1800)
        self.assertEqual(
            options["json_schema"]["properties"][
                "curation_fingerprint"
            ]["enum"],
            [fingerprint],
        )
        self.assertEqual(
            options["json_schema"]["properties"]["assignments"][
                "items"
            ]["properties"]["knowledge_id"]["enum"],
            [current["id"]],
        )

    def test_wrong_fingerprint_gets_one_fresh_recovery(self):
        current = self._akb_item()
        fingerprint = knowledge._curation_fingerprint(current)
        entry = {"knowledge_id": current["id"], "fingerprint": fingerprint}
        calls = []

        def model_call(prompt_path, payload, **_kwargs):
            packet = json.loads(payload)
            calls.append((prompt_path, packet, payload))
            plan = {
                "curation_fingerprint": "0" * 64,
                "assignments": [assignment(
                    current,
                    "akb48_ecosystem",
                    "AKB48",
                    subject_id="akb48",
                )],
                "reason": "First response has the wrong identity.",
            }
            if len(calls) == 2:
                self.assertNotIn("invalid_first_plan", packet)
                self.assertNotIn("四禧丸子", payload)
                plan["curation_fingerprint"] = packet[
                    "required_curation_fingerprint"
                ]
            return plan

        with (
            patch.object(knowledge, "load_items", return_value=[current]),
            patch.object(
                knowledge,
                "load_topic_catalog",
                return_value=[self._four_xi_topic(), self._akb_topic()],
            ),
        ):
            curator = KnowledgeCurator(model_call)
            result = curator._plan_batch([entry])

        self.assertEqual(len(result), 1)
        self.assertEqual(curator._last_plan_status, "RECOVERED_VALID")
        self.assertEqual([value[0] for value in calls], [
            "prompts/nerv_daily_knowledge_curator.txt",
            "prompts/nerv_daily_knowledge_curator_recovery.txt",
        ])
        self.assertEqual(calls[1][1]["contract_errors"], [
            "curation_fingerprint_mismatch"
        ])

    def test_cross_topic_model_memory_is_rejected_and_not_committed(self):
        current = self._akb_item()
        knowledge._save_knowledge([current])

        def wrong_model(_prompt_path, payload, **_kwargs):
            packet = json.loads(payload)
            wrong = item(
                current["id"],
                "四禧丸子",
                "四禧丸子是虚拟偶像团体。",
            )
            return {
                "curation_fingerprint": packet[
                    "required_curation_fingerprint"
                ],
                "assignments": [assignment(
                    wrong,
                    "sihixian_ecosystem",
                    "四禧丸子",
                    subject_id="sihixian_maruko",
                )],
                "reason": "Unrelated model-memory output.",
            }

        model = Mock(side_effect=wrong_model)
        result = KnowledgeCurator(model).run_once(force=True)

        self.assertEqual(result["status"], "FAILED")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(model.call_count, 2)
        self.assertIsNone(knowledge.load_topic_document("sihixian_ecosystem"))
        self.assertEqual(
            [value["knowledge_id"] for value in knowledge.load_curation_inbox(
                pending_only=True
            )],
            [current["id"]],
        )
        self.assertNotIn("curation", knowledge.load_items()[0])

    def test_one_item_failure_does_not_block_the_next_item(self):
        first = self._akb_item()
        second = item(
            "knowledge_manchester_united",
            "Manchester United",
            "Manchester United is an English football club.",
            ["Manchester United"],
        )
        knowledge._save_knowledge([first, second])
        calls = []

        def model_call(_prompt_path, payload, **_kwargs):
            packet = json.loads(payload)
            calls.append(packet["current_knowledge_id"])
            if packet["current_knowledge_id"] == first["id"]:
                return {
                    "curation_fingerprint": "f" * 64,
                    "assignments": [assignment(
                        first, "akb48_ecosystem", "AKB48",
                    )],
                    "reason": "Wrong fingerprint twice.",
                }
            return {
                "curation_fingerprint": packet[
                    "required_curation_fingerprint"
                ],
                "assignments": [assignment(
                    second,
                    "manchester_united",
                    "Manchester United",
                )],
                "reason": "Second item is valid.",
            }

        result = KnowledgeCurator(model_call).run_once(force=True)

        self.assertEqual(result["status"], "COMPLETED_WITH_ERRORS")
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["committed"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["primary_valid"], 1)
        self.assertEqual(calls, [first["id"], first["id"], second["id"]])
        pending = knowledge.load_curation_inbox(pending_only=True)
        self.assertEqual([value["knowledge_id"] for value in pending], [first["id"]])
        stored = {value["id"]: value for value in knowledge.load_items()}
        self.assertNotIn("curation", stored[first["id"]])
        self.assertEqual(
            stored[second["id"]]["curation"]["topic_id"],
            "manchester_united",
        )
        latest = knowledge.load_curator_runs()["runs"][-1]
        self.assertEqual(latest["status"], "COMPLETED_WITH_ERRORS")

    def test_four_live_akb_records_curate_only_into_akb_ecosystem(self):
        four_xi = item(
            "knowledge_sihixian_seed",
            "四禧丸子",
            "四禧丸子是虚拟偶像团体。",
            ["四禧丸子"],
        )
        akb_seed = item(
            "knowledge_akb_seed",
            "AKB48",
            "AKB48 operates a theater in Akihabara.",
            ["AKB48"],
        )
        knowledge._save_knowledge([four_xi, akb_seed])
        knowledge.apply_curator_assignments([
            assignment(
                four_xi,
                "sihixian_ecosystem",
                "四禧丸子",
                subject_id="sihixian_maruko",
            ),
            assignment(
                akb_seed,
                "akb48_ecosystem",
                "AKB48",
                subject_id="akb48",
            ),
        ])
        claims = [
            self._akb_item(
                "knowledge_akb_live_" + str(index),
                text,
            )
            for index, text in enumerate([
                "AKB48 is named after Akihabara, where its theater is located.",
                "AKB48's theater-centered concept lets fans meet its idols.",
                "AKB48 has used teams to organize simultaneous performances.",
                "AKB48 uses a graduation system for departing members.",
            ])
        ]
        knowledge._save_knowledge([*knowledge.load_items(), *claims])
        observed_topics = []

        def model_call(_prompt_path, payload, **_kwargs):
            packet = json.loads(payload)
            current_id = packet["current_knowledge_id"]
            current = next(value for value in claims if value["id"] == current_id)
            topic_ids = [
                value["topic_id"]
                for value in packet["relevant_topic_ecosystems"]
            ]
            observed_topics.append(topic_ids)
            self.assertIn("akb48_ecosystem", topic_ids)
            self.assertNotIn("sihixian_ecosystem", topic_ids)
            return {
                "curation_fingerprint": packet[
                    "required_curation_fingerprint"
                ],
                "assignments": [assignment(
                    current,
                    "akb48_ecosystem",
                    "AKB48",
                    subject_id="akb48",
                )],
                "reason": "Only the matching AKB48 ecosystem is supplied.",
            }

        result = KnowledgeCurator(model_call).run_once(force=True)

        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(result["processed"], 4)
        self.assertEqual(result["curated"], 4)
        self.assertEqual(result["primary_valid"], 4)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(observed_topics), 4)
        self.assertEqual(knowledge.load_curation_inbox(pending_only=True), [])
        stored = {value["id"]: value for value in knowledge.load_items()}
        self.assertTrue(all(
            stored[value["id"]]["curation"]["topic_id"]
            == "akb48_ecosystem"
            for value in claims
        ))
        self.assertEqual(
            len(knowledge.load_topic_document("sihixian_ecosystem")["claims"]),
            1,
        )
        self.assertEqual(
            len(knowledge.load_topic_document("akb48_ecosystem")["claims"]),
            5,
        )


class CuratorIsolationBuildTests(unittest.TestCase):
    def test_contract_versions_and_worker_diagnostics(self):
        self.assertEqual(knowledge_curator.MAX_BATCH_ITEMS, 1)
        self.assertEqual(knowledge_curator.CURATOR_PLAN_CONTRACT_VERSION, 2)
        self.assertEqual(knowledge_curator.CURATOR_ISOLATION_CONTRACT_VERSION, 1)
        self.assertEqual(knowledge_curator.MAX_CURATOR_PACKET_BYTES, 12000)
        self.assertEqual(
            knowledge_worker.KNOWLEDGE_WORKER_VERSION,
            "1.4.8-legacy-visual-backfill",
        )
        source = (ROOT / "knowledge_worker.py").read_text(encoding="utf-8")
        self.assertIn("knowledge_curator_plan_contract_version", source)
        self.assertIn("knowledge_curator_isolation_contract_version", source)

    def test_build_metadata_mirrors_prompts_and_validator(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Legacy Visual Evidence Backfill V1.10.54.8",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        for relative in (
            "knowledge.py", "knowledge_ai.py", "knowledge_worker.py",
            "knowledge_autonomy.py", "knowledge_scheduler.py",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
            )
        prompt = (
            ROOT / "prompts" / "nerv_daily_knowledge_curator.txt"
        ).read_text(encoding="utf-8")
        recovery = (
            ROOT / "prompts" / "nerv_daily_knowledge_curator_recovery.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("current_verified_item", prompt)
        self.assertIn("required_curation_fingerprint", prompt)
        self.assertIn("intentionally absent", recovery)
        self.assertNotIn("invalid first plan", recovery.casefold())
        self.assertTrue((
            ROOT / "TEST_KNOWLEDGE_CURATOR_ISOLATION_V1_10_54_3.ps1"
        ).is_file())
        self.assertTrue((
            ROOT / "KNOWLEDGE_CURATOR_ISOLATION_V1_10_54_3_NOTES.md"
        ).is_file())


if __name__ == "__main__":
    unittest.main()
