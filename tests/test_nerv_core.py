import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nerv.context_selector import ContextSelector
from nerv.core import NervCore
from nerv.learning_engine import LearningEngine
from nerv.profile_store import ProfileStore
from nerv.profile_writer import ProfileWriter


def proposal(**overrides):
    value = {
        "operation": "ADD",
        "category": "preference",
        "key": "restaurant_name_language",
        "value": "Keep restaurant names in their original language",
        "confidence": 0.96,
        "evidence_quote": "餐厅名字不要翻译",
        "sensitivity": "NORMAL",
        "reason": "The user explicitly stated a durable preference.",
    }
    value.update(overrides)
    return value


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ProfileStore(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_grounded_normal_proposal_becomes_active(self):
        result = self.store.apply(proposal(), "我一直觉得餐厅名字不要翻译")
        self.assertEqual(result["status"], "active")
        items = self.store.active_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["key"], "restaurant_name_language")

    def test_ungrounded_quote_is_rejected(self):
        result = self.store.apply(proposal(), "这是另一个完全不同的句子")
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(self.store.active_items(), [])

    def test_sensitive_proposal_waits_for_review(self):
        item = proposal(
            category="identity",
            key="government_identifier",
            value="123",
            evidence_quote="证件号码是123",
            sensitivity="SENSITIVE",
        )
        result = self.store.apply(item, "证件号码是123")
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(self.store.active_items(), [])

    def test_pending_update_does_not_replace_active_value(self):
        self.store.apply(proposal(), "餐厅名字不要翻译")
        result = self.store.apply(
            proposal(
                operation="UPDATE",
                value="Always translate restaurant names",
                confidence=0.60,
                evidence_quote="餐厅名字现在都翻译",
            ),
            "餐厅名字现在都翻译",
        )
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(
            self.store.active_items()[0]["value"],
            "Keep restaurant names in their original language",
        )

    def test_conflicting_add_waits_for_review(self):
        self.store.apply(proposal(), "餐厅名字不要翻译")
        result = self.store.apply(
            proposal(
                value="Always translate restaurant names",
                evidence_quote="餐厅名字都翻译",
            ),
            "餐厅名字都翻译",
        )
        self.assertEqual(result["status"], "pending_review")
        self.assertEqual(
            self.store.active_items()[0]["value"],
            "Keep restaurant names in their original language",
        )

    def test_explicit_remove_retains_audit_history(self):
        self.store.apply(proposal(), "餐厅名字不要翻译")
        result = self.store.apply(
            proposal(
                operation="REMOVE",
                value="",
                evidence_quote="忘掉餐厅名字不要翻译",
            ),
            "请忘掉餐厅名字不要翻译",
        )
        self.assertEqual(result["status"], "removed")
        self.assertEqual(self.store.active_items(), [])
        self.assertTrue((Path(self.temporary.name) / "data/nerv/audit.jsonl").exists())


class ContextSelectorTests(unittest.TestCase):
    def test_external_ai_receives_no_private_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            store.apply(proposal(), "餐厅名字不要翻译")
            selector = ContextSelector(store, temporary)
            self.assertEqual(selector.select("external_ai", "推荐餐厅"), [])

    def test_magi_receives_only_route_relevant_categories(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            store.apply(proposal(), "餐厅名字不要翻译")
            store.apply(
                proposal(
                    category="location",
                    key="home_region",
                    value="Arcadia",
                    evidence_quote="我住在Arcadia",
                ),
                "我住在Arcadia",
            )
            selected = ContextSelector(store, temporary).select("magi")
            self.assertEqual([item["category"] for item in selected], ["location"])

    def test_melchior_receives_active_preference_for_profile_answer(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            store.apply(proposal(), "餐厅名字不要翻译")
            selected = ContextSelector(store, temporary).select(
                "melchior", "我对餐厅名字有什么偏好？"
            )
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["category"], "preference")
            self.assertIn("original language", selected[0]["value"])


class ProfileWriterTests(unittest.TestCase):
    def test_ai_proposes_semantics_python_applies_contract(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            model_call = mock.Mock(return_value={"proposals": [proposal()]})
            result = ProfileWriter(store, model_call).process(
                "餐厅名字不要翻译"
            )
            self.assertEqual(result[0]["status"], "active")
            self.assertIn("nerv_profile_writer.txt", model_call.call_args.args[0])

    def test_missing_update_target_is_reconciled_as_store_lifecycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = ProfileStore(temporary)
            mistaken = proposal(operation="UPDATE")
            model_call = mock.Mock(return_value={"proposals": [mistaken]})
            results = ProfileWriter(store, model_call).process(
                "餐厅名字不要翻译"
            )
            self.assertEqual(model_call.call_count, 1)
            self.assertEqual(results[0]["status"], "active")
            self.assertEqual(len(store.active_items()), 1)

    def test_next_request_can_wait_for_async_profile_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            core = NervCore(
                model_call=mock.Mock(return_value={"proposals": [proposal()]}),
                unload_model=mock.Mock(),
                base_dir=temporary,
            )
            core.observe_completed_turn_async(
                "餐厅名字不要翻译", "LOCAL_ANSWER"
            )
            self.assertTrue(core.wait_for_pending_writes(timeout_seconds=2))
            self.assertEqual(len(core.profile.active_items()), 1)


class LearningEngineTests(unittest.TestCase):
    def test_observed_turn_never_becomes_verified_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            engine = LearningEngine(temporary)
            event = engine.record_result(
                "打开应用", "DEVICE_ACTION", "observed", action="opened_app"
            )
            self.assertEqual(event["state"], "OBSERVED")
            self.assertNotIn("request_excerpt", event)
            self.assertNotIn("打开应用", json.dumps(event, ensure_ascii=False))
            skills = json.loads(
                (Path(temporary) / "data/nerv/skills.json").read_text("utf-8")
            )
            self.assertEqual(skills["items"], [])

    def test_generic_verified_boolean_cannot_mint_verified_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            event = LearningEngine(temporary).record_result(
                "成功了", "DEVICE_ACTION", "verified", verified=True
            )
            self.assertEqual(event["state"], "OBSERVED")
            self.assertEqual(
                event["verification_claim"],
                "ignored_without_casper_receipt",
            )


class RuntimeIntegrationTests(unittest.TestCase):
    def test_main_initializes_nerv_and_keeps_magi_authority(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("nerv_core = NervCore", source)
        self.assertIn("magi.route_request(", source)
        self.assertIn("nerv_context=nerv_magi_context", source)
        self.assertIn("NERV is advisory state", source)

    def test_nerv_profile_reaches_final_writer_even_in_minimal_mode(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn(
            'nerv_profile_context = nerv_core.context_for("melchior", message)',
            source,
        )
        self.assertIn("NERV Governed Profile Context", source)
        self.assertIn("[NERV FINAL CONTEXT]", source)

        system_light = Path("prompts/system_light.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("does not restrict reading or using", system_light)
        self.assertIn("do not claim the information", system_light)

    def test_old_long_term_writer_is_disabled(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn('legacy_memory.get("type") == "temporary"', source)


if __name__ == "__main__":
    unittest.main()
