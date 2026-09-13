from pathlib import Path
import json
import sys
import types
import unittest
from unittest.mock import Mock, patch

import tools
from casper import browser
from nerv import external_fact_fallback


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-legacy-visual-backfill-v1-10-54-8-20260913"


class TemporalEvidenceGracefulFallbackTests(unittest.TestCase):
    def test_build_and_contract_files(self):
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))
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
            browser.TEMPORAL_EVIDENCE_GRACEFUL_FALLBACK_VERSION,
            1,
        )
        self.assertTrue(
            (ROOT / "prompts" / "fact_temporal_alternative_validate.txt").is_file()
        )

    def test_official_alternative_still_requires_identity_proof(self):
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(side_effect=AssertionError("must not call AI"))
        )
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._validate_temporal_alternative(
                "四禧丸子 2022年成员",
                {
                    "official_only": True,
                    "official_identity_verified": False,
                },
                "沐霂、又一、梨安、恬豆",
                {
                    "scope_type": "EXPLICIT_PERIOD",
                    "requested_period": "2022-01-15",
                },
                {
                    "time_scope_match": False,
                    "requested_period": "2022-01-15",
                    "source_period": "2024-02-09",
                },
            )
        self.assertFalse(result["accepted"])
        fake_tools.run_ai_prompt.assert_not_called()

    def test_mismatched_period_can_be_validated_for_display_only(self):
        verdict = {
            "accepted": True,
            "exact_entity_scope": True,
            "requested_fact_facet_match": True,
            "source_supported": True,
            "no_unsupported_additions": True,
            "explicit_source_period": True,
            "reason": "The official 2024 source directly lists the same roster facet.",
        }
        fake_tools = types.SimpleNamespace(
            run_ai_prompt=Mock(return_value=verdict)
        )
        source = {
            "title": "四禧丸子成员视频",
            "url": "https://www.bilibili.com/video/BV1official",
            "domain": "bilibili.com",
            "page_content": "沐霂是MUMU呀、恬豆发芽了、梨安不迷路、又一充电中",
            "official_only": True,
            "official_identity_verified": True,
        }
        with patch.dict(sys.modules, {"tools": fake_tools}):
            result = browser._validate_temporal_alternative(
                "四禧丸子 2022年成员",
                source,
                "沐霂是MUMU呀、恬豆发芽了、梨安不迷路、又一充电中",
                {
                    "scope_type": "EXPLICIT_PERIOD",
                    "requested_period": "2022-01-15",
                },
                {
                    "time_scope_match": False,
                    "requested_period": "2022-01-15",
                    "source_period": "2024-02-09",
                },
                user_request="请核实2022年1月15日的四位成员，只看官方",
            )
        self.assertTrue(result["accepted"])
        call = fake_tools.run_ai_prompt.call_args
        self.assertEqual(call.args[0], "prompts/fact_temporal_alternative_validate.txt")
        packet = json.loads(call.args[1])
        self.assertEqual(
            packet["temporal_validation"]["source_period"],
            "2024-02-09",
        )

    def test_explicit_period_fallback_uses_earliest_verified_result(self):
        fallback = browser._build_temporal_evidence_fallback(
            "请核实2022年1月15日四禧丸子的成员，只看官方资料",
            {
                "scope_type": "EXPLICIT_PERIOD",
                "requested_period": "2022-01-15",
            },
            [
                {
                    "index": 1,
                    "answer": "2024年5月名单",
                    "accepted": False,
                    "temporal_alternative_accepted": True,
                    "temporal_validation": {
                        "time_scope_match": False,
                        "requested_period": "2022-01-15",
                        "source_period": "2024-05-10",
                    },
                },
                {
                    "index": 2,
                    "answer": ["沐霂", "恬豆", "梨安", "又一"],
                    "accepted": False,
                    "temporal_alternative_accepted": True,
                    "temporal_validation": {
                        "time_scope_match": False,
                        "requested_period": "2022-01-15",
                        "source_period": "2024-02-09",
                    },
                },
            ],
            [
                {"title": "五月资料", "url": "https://example.test/may"},
                {"title": "二月资料", "url": "https://example.test/feb"},
            ],
            {"official_only": True},
        )
        self.assertEqual(
            fallback["selection"],
            "EARLIEST_VERIFIED_ALTERNATIVE",
        )
        self.assertEqual(
            fallback["selected_evidence"]["source_period"],
            "2024-02-09",
        )
        self.assertIn("没有查到能直接核实 2022-01-15", fallback["reply"])
        self.assertIn("最早官方资料是 2024-02-09", fallback["reply"])
        self.assertIn("沐霂、恬豆、梨安、又一", fallback["reply"])
        self.assertIn("不能当作 2022-01-15 的结论", fallback["reply"])
        self.assertFalse(fallback["knowledge_eligible"])
        self.assertFalse(fallback["target_scope_answered"])

    def test_current_query_uses_latest_verified_alternative(self):
        fallback = browser._build_temporal_evidence_fallback(
            "四禧丸子现在的成员是谁",
            {"scope_type": "CURRENT_ACTIVE_STATE"},
            [
                {
                    "index": 1,
                    "answer": "2023年的成员资料",
                    "accepted": False,
                    "temporal_alternative_accepted": True,
                    "temporal_validation": {
                        "time_scope_match": False,
                        "requested_period": "current",
                        "source_period": "2023-07-01",
                    },
                },
                {
                    "index": 2,
                    "answer": "2024年的成员资料",
                    "accepted": False,
                    "temporal_alternative_accepted": True,
                    "temporal_validation": {
                        "time_scope_match": False,
                        "requested_period": "current",
                        "source_period": "2024-02-09",
                    },
                },
            ],
            [{"title": "2023"}, {"title": "2024"}],
            {"official_only": False},
        )
        self.assertEqual(
            fallback["selection"],
            "LATEST_VERIFIED_ALTERNATIVE",
        )
        self.assertEqual(
            fallback["selected_evidence"]["source_period"],
            "2024-02-09",
        )
        self.assertIn("当前状态", fallback["reply"])
        self.assertIn("最新资料是 2024-02-09", fallback["reply"])

    def test_controller_returns_useful_fallback_without_accepting_2024_as_2022(self):
        candidates = [
            {
                "title": "2024年5月官方成员视频",
                "description": "成员名单",
                "domain": "bilibili.com",
                "url": "https://www.bilibili.com/video/BV1may",
                "published": "2024-05-10",
                "official_only": True,
                "official_identity_verified": True,
            },
            {
                "title": "2024年2月官方成员视频",
                "description": "成员名单",
                "domain": "bilibili.com",
                "url": "https://www.bilibili.com/video/BV1feb",
                "published": "2024-02-09",
                "official_only": True,
                "official_identity_verified": True,
            },
        ]
        scope = {
            "scope_type": "EXPLICIT_PERIOD",
            "requested_period": "2022-01-15",
            "allow_previous_period": False,
        }
        entity_scope = {
            "target_entity": "四禧丸子",
            "requested_relation": "四位成员",
            "required_facets": ["成员名单"],
            "included_scope": "四禧丸子官方账号",
            "excluded_adjacent_scopes": ["粉丝账号"],
            "source_language_boundaries": [
                {"source_expression": "四禧丸子"}
            ],
        }
        audit = {
            "approved_search_query": "四禧丸子 2022年1月15日 成员",
            "decision": "USE",
        }
        temporal_results = [
            {
                "time_scope_match": False,
                "requested_period": "2022-01-15",
                "source_period": "2024-05-10",
                "reason": "Later official source.",
            },
            {
                "time_scope_match": False,
                "requested_period": "2022-01-15",
                "source_period": "2024-02-09",
                "reason": "Later official source.",
            },
        ]
        with patch.object(
            browser, "_plan_fact_intent_scope", return_value=scope
        ), patch.object(
            browser, "_plan_fact_entity_scope", return_value=entity_scope
        ), patch.object(
            browser, "_audit_fact_search_query", return_value=audit
        ), patch.object(
            browser,
            "_discover_native_fixed_fact_candidates",
            return_value={"status": "OK", "results": candidates},
        ), patch.object(
            browser, "_try_search_summary_fact_answer", return_value=None
        ), patch.object(
            tools, "score_sources", side_effect=lambda _query, values: values
        ), patch.object(
            browser,
            "_read_native_fact_candidate",
            side_effect=[
                {"success": True, "content": "五月官方成员名单"},
                {"success": True, "content": "二月官方成员名单"},
            ],
        ), patch.object(
            tools,
            "extract_answers",
            side_effect=[
                [{"answer": "沐霂、恬豆、梨安、又一"}],
                [{"answer": "沐霂、恬豆、梨安、又一"}],
            ],
        ), patch.object(
            browser,
            "_validate_temporal_scope",
            side_effect=temporal_results,
        ), patch.object(
            browser,
            "_validate_temporal_alternative",
            return_value={"accepted": True, "reason": "display only"},
        ) as alternative_validator, patch.object(
            browser,
            "_plan_evidence_gap",
            return_value={"action": "RESOLVE_NOW", "follow_up_queries": []},
        ), patch.object(
            browser,
            "_resolve_combined_fact",
            return_value={
                "answer_status": "INSUFFICIENT",
                "accepted": False,
                "reason": "No exact 2022 evidence.",
            },
        ):
            result = browser.fact_lookup_controller(
                "四禧丸子 2022年1月15日 成员",
                user_request=(
                    "请去B站核实四禧丸子2022年1月15日的成员，只看官方"
                ),
                requested_sites=["bilibili.com"],
                official_only=True,
                risk="low",
            )

        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["answer_kind"], "TEMPORAL_EVIDENCE_FALLBACK")
        self.assertFalse(result["target_scope_answered"])
        self.assertFalse(result["knowledge_capture_eligible"])
        self.assertTrue(result["direct_reply"])
        self.assertIn("2022-01-15", result["direct_reply"])
        self.assertIn("2024-02-09", result["direct_reply"])
        self.assertTrue(all(item["accepted"] is False for item in result["answers"]))
        self.assertFalse(
            result["temporal_evidence_fallback"]["knowledge_eligible"]
        )
        alternative_validator.assert_called_once()
        self.assertEqual(
            alternative_validator.call_args.args[1]["title"],
            "2024年2月官方成员视频",
        )

    def test_no_validated_alternative_keeps_the_fallback_closed(self):
        fallback = browser._build_temporal_evidence_fallback(
            "2022年的资料",
            {"scope_type": "EXPLICIT_PERIOD", "requested_period": "2022"},
            [],
            [],
            {},
        )
        self.assertIsNone(fallback)

    def test_display_only_fallback_cannot_enter_fact_knowledge_intake(self):
        result = external_fact_fallback.intake_audited_fact_lookup(
            "请核实2022年的成员",
            "2022没有查到；最早可核实资料是2024年。",
            {
                "status": "OK",
                "answer_kind": "TEMPORAL_EVIDENCE_FALLBACK",
                "target_scope_answered": False,
                "knowledge_capture_eligible": False,
                "answers": [
                    {
                        "answer": "沐霂、恬豆、梨安、又一",
                        "accepted": False,
                        "temporal_alternative_accepted": True,
                    }
                ],
            },
            risk="low",
        )
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(result["reason"], "display_only_temporal_evidence")


if __name__ == "__main__":
    unittest.main()
