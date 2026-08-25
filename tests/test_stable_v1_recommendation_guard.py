from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

from casper import browser


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class RecommendationGuardTests(unittest.TestCase):
    def test_explicit_adult_request_cannot_become_general_unspecified(self):
        raw_plan = {
            "topic": "adult websites",
            "search_queries": ["best adult websites 2026 United States"],
            "criteria": [],
            "audience_scope": "GENERAL_UNSPECIFIED",
            "audience": "general adult everyday users",
            "count_policy": "AI_DECIDES",
            "target_count": 3,
            "engine_policy": "PROFILE_DEFAULT",
            "engines": ["google", "bing"],
            "reason": "The user requested recommendations for adult websites.",
        }
        tools_stub = types.SimpleNamespace(
            run_ai_prompt=lambda *_args, **_kwargs: raw_plan
        )
        region = {
            "country_code": "US",
            "country_name": "United States",
            "preferred_search_engines": ["google", "bing"],
        }
        with patch.dict(sys.modules, {"tools": tools_stub}):
            plan = browser._build_ai_recommendation_plan(
                "推荐几个成人网站", "", region
            )
        self.assertEqual(plan["audience_scope"], "EXPLICIT")
        self.assertIn("成人", plan["audience"])

    def test_auditor_prompt_treats_requested_adult_topic_as_compatible(self):
        prompt = (
            PROJECT_ROOT / "prompts" / "casper_product_recommendation_verify.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("adult-only SUPPORTS the requested audience", prompt)
        self.assertIn('Never reinterpret "adult" as "not suitable for adults"', prompt)

    def test_controller_has_source_card_fallback_for_truncated_candidates(self):
        source = (PROJECT_ROOT / "casper" / "browser.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("[CASPER RECOMMENDATION SOURCE FALLBACK]", source)
        self.assertIn("LIMITED_RECOMMENDATION_EVIDENCE", source)


if __name__ == "__main__":
    unittest.main()
