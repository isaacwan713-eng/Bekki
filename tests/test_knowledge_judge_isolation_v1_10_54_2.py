import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import knowledge
import knowledge_ai
import knowledge_worker


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


def candidate():
    return {
        "subject": "AKB48",
        "claim": (
            "AKB48 uses a theater-centered operating model and is organized "
            "into teams."
        ),
        "topics": ["AKB48", "idol group"],
        "published_at": None,
        "knowledge_type": "stable",
        "lifecycle_basis": (
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
        ),
        "suggested_valid_for_days": None,
        "temporal_scope": {},
        "confidence": 0.95,
        "risk": "low",
    }


def source():
    return {
        "name": "Wikipedia AKB48",
        "url": "https://en.wikipedia.org/wiki/AKB48",
        "domain": "en.wikipedia.org",
        "topics": ["AKB48"],
        "trust": "established_reference",
        "trust_score": 0.9,
        "status": "approved",
    }


def valid_judgment(fingerprint, action="AUTO_SAVE", target_id=None):
    return {
        "candidate_fingerprint": fingerprint,
        "action": action,
        "target_id": target_id,
        "knowledge_type": "stable",
        "lifecycle_basis": (
            "DURABLE_EXPLANATION_DEFINITION_OR_MECHANISM"
        ),
        "valid_for_days": None,
        "temporal_scope": {},
        "confidence": 0.95,
        "risk": "low",
        "reason": "The approved source directly supports the candidate.",
    }


class KnowledgeJudgePromptIsolationTests(unittest.TestCase):
    def test_only_relevant_compact_knowledge_reaches_primary_judge(self):
        item = candidate()
        fingerprint = knowledge_ai._candidate_fingerprint(item)
        relevant = {
            "id": fingerprint,
            "subject": "AKB48",
            "claim": item["claim"],
            "topics": ["akb48"],
            "status": "pending_review",
            "knowledge_type": "stable",
            "huge_internal_blob": "relevant-secret-noise" * 10000,
        }
        unrelated = [
            {
                "id": "knowledge_unrelated_" + str(index),
                "subject": "四禧丸子",
                "claim": "四禧丸子旧内容" + str(index),
                "topics": ["四禧丸子"],
                "status": "verified",
                "huge_internal_blob": "unrelated-secret-noise" * 10000,
            }
            for index in range(80)
        ]
        calls = []

        def model_call(prompt_path, input_text, **kwargs):
            calls.append((prompt_path, input_text, kwargs))
            return valid_judgment(
                fingerprint,
                action="UPDATE",
                target_id=fingerprint,
            )

        with (
            patch.object(knowledge_ai.knowledge, "load_items", return_value=unrelated + [relevant]),
            patch.object(knowledge_ai.tools, "run_ai_prompt", side_effect=model_call),
        ):
            result = knowledge_ai.judge_knowledge(item, source())

        self.assertEqual(result["_judge_output_status"], "PRIMARY_VALID")
        self.assertEqual(len(calls), 1)
        prompt_path, rendered, options = calls[0]
        self.assertEqual(prompt_path, "prompts/knowledge_judge.txt")
        self.assertLess(len(rendered.encode("utf-8")), 18000)
        self.assertIn(fingerprint, rendered)
        self.assertIn("pending_review", rendered)
        self.assertNotIn("四禧丸子旧内容", rendered)
        self.assertNotIn("unrelated-secret-noise", rendered)
        self.assertNotIn("relevant-secret-noise", rendered)
        self.assertEqual(
            options["json_schema"]["properties"]["candidate_fingerprint"]["enum"],
            [fingerprint],
        )

    def test_invalid_primary_gets_one_history_free_compact_recovery(self):
        item = candidate()
        fingerprint = knowledge_ai._candidate_fingerprint(item)
        calls = []

        def model_call(prompt_path, input_text, **kwargs):
            calls.append((prompt_path, input_text, kwargs))
            if len(calls) == 1:
                return None
            return valid_judgment(fingerprint)

        existing = [{
            "id": fingerprint,
            "subject": "AKB48",
            "claim": item["claim"],
            "topics": ["AKB48"],
            "status": "pending_review",
        }]
        with (
            patch.object(knowledge_ai.knowledge, "load_items", return_value=existing),
            patch.object(knowledge_ai.tools, "run_ai_prompt", side_effect=model_call),
        ):
            result = knowledge_ai.judge_knowledge(item, source())

        self.assertEqual(result["_judge_output_status"], "RECOVERED_VALID")
        self.assertEqual([value[0] for value in calls], [
            "prompts/knowledge_judge.txt",
            "prompts/knowledge_judge_recover.txt",
        ])
        self.assertIn('"relevant_existing_knowledge":[]', calls[1][1])
        self.assertNotIn("pending_review", calls[1][1])
        self.assertLess(len(calls[1][1].encode("utf-8")), 10000)

    def test_wrong_candidate_fingerprint_triggers_recovery(self):
        item = candidate()
        fingerprint = knowledge_ai._candidate_fingerprint(item)
        wrong = valid_judgment("knowledge_wrong")
        with (
            patch.object(knowledge_ai.knowledge, "load_items", return_value=[]),
            patch.object(
                knowledge_ai.tools,
                "run_ai_prompt",
                side_effect=[wrong, valid_judgment(fingerprint)],
            ) as model_call,
        ):
            result = knowledge_ai.judge_knowledge(item, source())
        self.assertEqual(model_call.call_count, 2)
        self.assertEqual(result["_judge_output_status"], "RECOVERED_VALID")

    def test_two_invalid_outputs_fail_closed_with_diagnostic(self):
        with (
            patch.object(knowledge_ai.knowledge, "load_items", return_value=[]),
            patch.object(
                knowledge_ai.tools,
                "run_ai_prompt",
                side_effect=[None, None],
            ) as model_call,
        ):
            result = knowledge_ai.judge_knowledge(candidate(), source())
        self.assertEqual(model_call.call_count, 2)
        self.assertEqual(result["action"], "PENDING_REVIEW")
        self.assertEqual(result["_judge_output_status"], "INVALID_JSON")
        self.assertEqual(result["_judge_contract_version"], 2)


class PendingIdentityStorageTests(unittest.TestCase):
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
    def invalid_judgment():
        value = valid_judgment(
            knowledge_ai._candidate_fingerprint(candidate()),
            action="PENDING_REVIEW",
        )
        value["confidence"] = 0.0
        value["risk"] = "medium"
        value["reason"] = "Judge JSON was invalid after recovery."
        value["_judge_output_status"] = "INVALID_JSON"
        value["_judge_contract_version"] = 2
        return value

    def test_repeated_invalid_judgment_does_not_duplicate_pending_id(self):
        first, _ = knowledge.apply_knowledge_judgment(
            candidate(), source(), self.invalid_judgment()
        )
        second, _ = knowledge.apply_knowledge_judgment(
            candidate(), source(), self.invalid_judgment()
        )
        stored = knowledge.load_items()
        self.assertEqual((first, second), ("pending_review", "pending_review"))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["status"], "pending_review")
        self.assertEqual(stored[0]["pending_identity_contract_version"], 1)

    def test_valid_autosave_promotes_pending_item_in_place(self):
        knowledge.apply_knowledge_judgment(
            candidate(), source(), self.invalid_judgment()
        )
        judgment = valid_judgment(
            knowledge_ai._candidate_fingerprint(candidate())
        )
        judgment["_judge_output_status"] = "PRIMARY_VALID"
        judgment["_judge_contract_version"] = 2
        result, promoted = knowledge.apply_knowledge_judgment(
            candidate(), source(), judgment
        )
        stored = knowledge.load_items()
        self.assertEqual(result, "updated")
        self.assertEqual(len(stored), 1)
        self.assertEqual(promoted["status"], "verified")
        self.assertEqual(stored[0]["knowledge_judge_output_status"], "PRIMARY_VALID")

    def test_exact_verified_autosave_is_structurally_deduplicated(self):
        judgment = valid_judgment(
            knowledge_ai._candidate_fingerprint(candidate())
        )
        judgment["_judge_output_status"] = "PRIMARY_VALID"
        judgment["_judge_contract_version"] = 2
        first, _ = knowledge.apply_knowledge_judgment(
            candidate(), source(), judgment
        )
        second, existing = knowledge.apply_knowledge_judgment(
            candidate(), source(), judgment
        )
        self.assertEqual(first, "verified")
        self.assertEqual(second, "duplicate")
        self.assertEqual(existing["status"], "verified")
        self.assertEqual(len(knowledge.load_items()), 1)

    def test_invalid_event_output_cannot_be_counted_as_log_only_evidence(self):
        event_candidate = candidate()
        event_candidate["knowledge_type"] = "event"
        event_candidate["lifecycle_basis"] = (
            "TRANSIENT_CURRENT_STATE_OR_EVENT"
        )
        judgment = self.invalid_judgment()
        judgment["knowledge_type"] = "event"
        judgment["lifecycle_basis"] = "TRANSIENT_CURRENT_STATE_OR_EVENT"
        result, retained = knowledge.apply_knowledge_judgment(
            event_candidate, source(), judgment
        )
        self.assertEqual(result, "pending_review")
        self.assertEqual(retained["knowledge_type"], "event")
        self.assertEqual(knowledge.load_items(), [])


class JudgeCycleDiagnosticsTests(unittest.TestCase):
    def test_wikipedia_ranks_before_fandom_and_namu(self):
        values = [
            {"domain": "akb48.fandom.com", "url": "https://akb48.fandom.com/wiki/AKB48"},
            {"domain": "en.namu.wiki", "url": "https://en.namu.wiki/w/AKB48"},
            {"domain": "en.wikipedia.org", "url": "https://en.wikipedia.org/wiki/AKB48"},
        ]
        ranked = sorted(values, key=knowledge_worker._source_priority)
        self.assertEqual(ranked[0]["domain"], "en.wikipedia.org")
        self.assertEqual(
            {value["domain"] for value in ranked[1:]},
            {"akb48.fandom.com", "en.namu.wiki"},
        )

    def test_invalid_judge_json_has_precise_no_evidence_reason(self):
        item = candidate()
        invalid = PendingIdentityStorageTests.invalid_judgment()
        plan = {
            "mode": "OPEN_GAP",
            "reason": "Open gap.",
            "selected_topic_ids": ["akb48_ecosystem"],
            "selected_topics": [{
                "topic_id": "akb48_ecosystem",
                "title": "AKB48",
                "aliases": [],
            }],
        }
        with (
            patch.object(knowledge_worker.knowledge, "initialize"),
            patch.object(knowledge_worker.knowledge, "load_items", return_value=[]),
            patch.object(knowledge_worker, "choose_sources", return_value=[source()]),
            patch.object(
                knowledge_worker,
                "review_source_candidates",
                return_value={"approved": 0, "pending": 0, "rejected": 0, "errors": 0},
            ),
            patch.object(knowledge_worker, "read_source", return_value="evidence" * 100),
            patch.object(knowledge_worker, "extract_candidates", return_value=[item]),
            patch.object(knowledge_worker.knowledge_ai, "judge_knowledge", return_value=invalid),
            patch.object(
                knowledge_worker.knowledge,
                "apply_knowledge_judgment",
                return_value=("pending_review", item),
            ),
            patch.object(
                knowledge_worker,
                "organize_learned_knowledge",
                return_value={"status": "SKIPPED"},
            ),
            patch.object(knowledge_worker.knowledge, "append_learning_log"),
        ):
            log = knowledge_worker.run_learning_cycle(
                topics=["AKB48"], autonomy_plan=plan, trigger="windows_scheduler"
            )
        self.assertEqual(log["status"], "NO_VERIFIED_EVIDENCE")
        self.assertEqual(log["candidates_extracted"], 1)
        self.assertEqual(log["knowledge_judge"]["invalid_json"], 1)
        self.assertEqual(log["errors"], 1)
        self.assertIn("Knowledge Judge", log["outcome_reason"])
        self.assertNotIn("No approved readable source", log["outcome_reason"])


class JudgeIsolationBuildTests(unittest.TestCase):
    def test_build_metadata_mirrors_and_docs(self):
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
        for relative in (
            "knowledge.py", "knowledge_ai.py", "knowledge_worker.py",
            "knowledge_autonomy.py", "knowledge_scheduler.py",
        ):
            self.assertEqual(
                (ROOT / relative).read_bytes(),
                (ROOT / "casper" / relative).read_bytes(),
            )
        self.assertTrue(
            (ROOT / "TEST_KNOWLEDGE_JUDGE_ISOLATION_V1_10_54_2.ps1").is_file()
        )
        self.assertTrue(
            (ROOT / "KNOWLEDGE_JUDGE_ISOLATION_V1_10_54_2_NOTES.md").is_file()
        )
        self.assertTrue(
            (ROOT / "prompts" / "knowledge_judge_recover.txt").is_file()
        )


if __name__ == "__main__":
    unittest.main()
