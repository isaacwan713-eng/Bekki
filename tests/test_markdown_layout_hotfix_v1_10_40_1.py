from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import tools
from casper import browser


ROOT = Path(__file__).resolve().parents[1]


class MarkdownLayoutHotfixV110401Tests(unittest.TestCase):
    def test_message_bubbles_use_document_measurement_and_top_alignment(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("def _measure_markdown_bubble(", source)
        self.assertIn("documentLayout().documentSize().height()", source)
        self.assertIn("Qt.AlignLeft | Qt.AlignTop", source)
        self.assertIn("dynamic_width=self._is_user_message", source)
        self.assertNotIn("self.bubble.heightForWidth", source)

    def test_message_geometry_refresh_is_deferred_after_result_handoff(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertIn("def _schedule_geometry_refresh(self):", source)
        self.assertIn("QTimer.singleShot(0, self._finish_geometry_refresh)", source)
        self.assertIn("self._schedule_geometry_refresh()", source)

    def test_root_and_casper_ui_remain_exact_mirrors(self):
        self.assertEqual(
            (ROOT / "ui.py").read_bytes(),
            (ROOT / "casper" / "ui.py").read_bytes(),
        )

    def test_recovery_sources_are_fresh_and_reenter_candidate_audit(self):
        plan = {
            "topic": "insulated straw bottle",
            "search_queries": ["initial independent bottle reviews"],
            "criteria": ["about 500 ml", "keeps cold 12 hours", "under $50"],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general everyday users",
            "count_policy": "USER_EXPLICIT",
            "target_count": 1,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ("google", "bing"),
            "reason": "User requested one bottle.",
        }
        initial_sources = [
            {
                "index": 1,
                "domain": "reviews.example",
                "title": "Initial bottle review",
                "description": "Initial evidence",
                "url": "https://reviews.example/initial",
            }
        ]
        recovery_sources = [
            {
                "index": 1,
                "domain": "reviews.example",
                "title": "Different bottle review",
                "description": "Recovery evidence from a reused editorial domain",
                "url": "https://reviews.example/recovery",
            }
        ]
        initial_option = {
            "title": "Rejected Bottle",
            "brand": "Rejected",
            "summary": "Initial candidate",
            "verification_queries": ["Rejected Bottle specifications"],
            "url": "https://reviews.example/initial",
            "domain": "reviews.example",
            "source_count": 1,
            "source_domains": ["reviews.example"],
            "evidence": [],
        }
        recovery_option = {
            "title": "Recovered Bottle",
            "brand": "Recovered",
            "summary": "Recovery candidate",
            "verification_queries": ["Recovered Bottle specifications"],
            "url": "https://reviews.example/recovery",
            "domain": "reviews.example",
            "source_count": 1,
            "source_domains": ["reviews.example"],
            "evidence": [],
        }
        verified = {
            **recovery_option,
            "verification_source_count": 1,
            "verification_source_domains": ["verification.example"],
        }
        rejected = {
            "candidate_id": 1,
            "title": "Rejected Bottle",
            "verdict": "FAIL",
            "reason": "The budget condition was not verified.",
            "failed_conditions": ["under $50"],
        }
        region = {
            "country_code": "US",
            "country_name": "United States",
            "preferred_search_engines": ["google", "bing"],
        }
        fake_cards = types.SimpleNamespace(clean_cards=lambda values: list(values))
        fake_region = types.SimpleNamespace(detect_shopping_region=lambda: region)
        fake_location = types.SimpleNamespace(detect_location=lambda: region)

        with patch.object(
            browser, "_build_ai_recommendation_plan", return_value=plan
        ), patch.object(
            browser,
            "_collect_recommendation_sources",
            side_effect=[(initial_sources, "OK"), (recovery_sources, "OK")],
        ) as collect, patch.object(
            browser,
            "_ask_ai_for_recommendation_options",
            side_effect=[([initial_option], ""), ([recovery_option], "")],
        ) as candidates, patch.object(
            browser,
            "_verify_ai_recommendation_options",
            side_effect=[([], [rejected]), ([verified], [])],
        ) as verify, patch.object(
            browser,
            "_build_ai_recommendation_recovery_queries",
            return_value=["fresh recovery review query under $50"],
        ), patch.object(
            browser,
            "_build_ai_verified_recommendation_reply",
            return_value="### 推荐结果\n\n- Recovered Bottle",
        ), patch.object(
            tools, "unload_model"
        ), patch.dict(
            sys.modules,
            {
                "result_cards": fake_cards,
                "shopping_region": fake_region,
                "location": fake_location,
            },
        ):
            result = browser.product_recommendation_controller("推荐一个水杯")

        self.assertEqual(collect.call_count, 2)
        self.assertIsNone(collect.call_args_list[1].kwargs["existing_sources"])
        self.assertEqual(candidates.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["results"][0]["title"], "Recovered Bottle")
        self.assertIn("Recovered Bottle", result["direct_reply"])

    def test_zero_verified_candidates_still_return_a_real_markdown_answer(self):
        reply = browser._build_recommendation_shortfall_reply(
            "推荐三个水杯",
            {"target_count": 3},
            [
                {
                    "title": "Bottle A",
                    "reason": "没有证据确认 12 小时保冷。",
                    "failed_conditions": ["12 小时保冷"],
                }
            ],
            source_count=3,
        )
        self.assertIn("### 这次还没有足够的已验证推荐", reply)
        self.assertIn("Bottle A", reply)
        self.assertIn("不是已验证推荐", reply)

    def test_explicit_budget_can_use_non_live_price_evidence(self):
        options = (
            ROOT / "prompts" / "casper_product_recommendation_options.txt"
        ).read_text(encoding="utf-8")
        verify = (
            ROOT / "prompts" / "casper_product_recommendation_verify.txt"
        ).read_text(encoding="utf-8")
        recovery = (
            ROOT / "prompts" / "casper_product_recommendation_recovery.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("official manufacturer MSRP/list price", options)
        self.assertIn("official manufacturer MSRP/list price", verify)
        self.assertIn("official MSRP/list-price query", recovery)


if __name__ == "__main__":
    unittest.main()
