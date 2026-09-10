import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

import social_browser
import source_scope
from casper import browser


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class SiteQueryIdempotenceTests(unittest.TestCase):
    def test_fixed_site_operator_is_idempotent(self):
        query = 'site:bilibili.com "四禧丸子" 成员'
        self.assertEqual(
            source_scope.constrain_query(query, ["bilibili.com"]),
            query,
        )
        duplicate = 'site:bilibili.com site:bilibili.com "四禧丸子" 成员'
        self.assertEqual(
            source_scope.constrain_query(duplicate, ["bilibili.com"]),
            query,
        )

    def test_unapproved_site_operator_is_replaced(self):
        self.assertEqual(
            source_scope.constrain_query(
                'site:example.net "四禧丸子" 成员',
                ["bilibili.com"],
            ),
            'site:bilibili.com "四禧丸子" 成员',
        )

    def test_native_query_removes_engine_and_leading_site_syntax(self):
        self.assertEqual(
            source_scope.native_site_query(
                'site:bilibili.com Bilibili "四禧丸子" 官方简介',
                "bilibili.com",
            ),
            "四禧丸子 官方简介",
        )


class BilibiliProfileCandidateTests(unittest.TestCase):
    class FakeFrame:
        def evaluate(self, _script):
            return [
                {
                    "url": "https://space.bilibili.com/123456",
                    "visible_text": "四禧丸子_Official 虚拟偶像团体",
                    "image_url": "https://i0.hdslb.com/avatar.jpg",
                    "image_alt": "四禧丸子",
                    "source_kind": "result_card",
                    "profile_name": "四禧丸子_Official",
                    "profile_result_matched": True,
                    "profile_verified": True,
                },
                {
                    "url": "https://www.bilibili.com/video/BV1nativefact",
                    "visible_text": "四禧丸子官方成员介绍",
                    "image_url": "https://i0.hdslb.com/cover.jpg",
                    "image_alt": "成员介绍",
                    "source_kind": "result_card",
                },
            ]

    class FakePage:
        frames = []

    def setUp(self):
        self.page = self.FakePage()
        self.page.frames = [self.FakeFrame()]

    def test_profile_candidates_are_fact_only_opt_in(self):
        social_candidates = social_browser._extract_post_candidates(
            self.page,
            "bilibili",
        )
        fact_candidates = social_browser._extract_post_candidates(
            self.page,
            "bilibili",
            include_profile_candidates=True,
        )
        self.assertEqual(len(social_candidates), 1)
        self.assertIn("/video/", social_candidates[0]["url"])
        self.assertEqual(len(fact_candidates), 2)
        self.assertEqual(
            fact_candidates[0]["url"],
            "https://space.bilibili.com/123456",
        )
        self.assertEqual(fact_candidates[0]["source_kind"], "profile_result")


class BilibiliNativeFactDiscoveryTests(unittest.TestCase):
    def test_native_discovery_uses_site_query_and_keeps_real_urls(self):
        profile_url = "https://search.bilibili.com/upuser?keyword=x"
        content_url = "https://search.bilibili.com/all?keyword=x"
        profile_page = {
            "post_candidates": [
                {
                    "url": "https://space.bilibili.com/123456",
                    "title": "四禧丸子_Official",
                    "visible_text": "四禧丸子_Official 虚拟偶像团体",
                    "source_kind": "profile_result",
                    "profile_name": "四禧丸子_Official",
                    "profile_result_matched": True,
                    "profile_verified": True,
                },
            ]
        }
        content_page = {
            "post_candidates": [
                {
                    "url": "https://www.bilibili.com/video/BV1official",
                    "title": "四禧丸子官方成员介绍",
                    "visible_text": "四禧丸子官方成员介绍",
                    "source_kind": "result_card",
                    "author": "四禧丸子_Official",
                    "author_url": "https://space.bilibili.com/123456",
                },
                {
                    "url": "https://evil.example/video/1",
                    "title": "越界结果",
                    "visible_text": "不允许",
                },
            ]
        }
        with patch.object(
            social_browser,
            "open_social_search",
            side_effect=[{"url": profile_url}, {"url": content_url}],
        ) as opened, patch.object(
            social_browser,
            "inspect_active_social_page",
            side_effect=[profile_page, content_page],
        ) as inspected, patch.object(
            social_browser,
            "close_social_search",
        ), patch.object(
            browser,
            "_discover_bilibili_verified_publisher_videos",
            return_value=[],
        ), patch.object(browser.time, "sleep", return_value=None):
            result = browser._discover_native_fixed_fact_candidates(
                'site:bilibili.com Bilibili "四禧丸子" 官方账号',
                ["bilibili.com"],
                official_only=True,
            )
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["native_query"], "四禧丸子 官方账号")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["native_platform"], "bilibili")
        self.assertTrue(result["results"][0]["official_identity_verified"])
        self.assertEqual(opened.call_count, 2)
        self.assertEqual(opened.call_args_list[0].args, ("bilibili", "四禧丸子"))
        self.assertEqual(opened.call_args_list[0].kwargs["search_kind"], "profile")
        self.assertEqual(opened.call_args_list[1].kwargs["search_kind"], "all")
        self.assertTrue(
            inspected.call_args_list[0].kwargs["include_profile_candidates"]
        )

    def test_supported_native_scope_does_not_widen_when_empty(self):
        fact_scope = {"temporal_scope": "CURRENT"}
        entity_scope = {"included_scope": "四禧丸子"}
        audit = {"approved_search_query": "四禧丸子 当前成员"}
        tools_stub = types.SimpleNamespace()
        with patch.dict(sys.modules, {"tools": tools_stub}), patch.object(
            browser, "_plan_fact_intent_scope", return_value=fact_scope
        ), patch.object(
            browser, "_plan_fact_entity_scope", return_value=entity_scope
        ), patch.object(
            browser, "_audit_fact_search_query", return_value=audit
        ), patch.object(
            browser,
            "_discover_native_fixed_fact_candidates",
            return_value={
                "status": "NO_RESULTS",
                "results": [],
                "discovery_type": "site_native_fact",
            },
        ), patch.object(
            browser,
            "discover_web",
            side_effect=AssertionError("native fixed scope must not widen"),
        ):
            result = browser.fact_lookup_controller(
                "四禧丸子 当前成员",
                user_request="请去B站核实，只看官方账号",
                requested_sites=["bilibili.com"],
                official_only=True,
            )
        self.assertEqual(result["status"], "NO_RESULTS")
        self.assertEqual(
            result["external_ai_fallback"]["reason"],
            "fixed_source_scope",
        )

    def test_video_reader_uses_bounded_native_detail(self):
        candidate = {
            "native_platform": "bilibili",
            "url": "https://www.bilibili.com/video/BV1nativefact",
            "title": "四禧丸子成员介绍",
            "native_visible_text": "搜索卡片文字",
        }
        with patch.object(
            social_browser,
            "inspect_social_post_details",
            return_value=[
                {
                    "url": candidate["url"],
                    "visible_text": (
                        "CURRENT VIDEO:\n标题: 四禧丸子成员介绍\n"
                        "UP主: 四禧丸子_Official"
                    ),
                    "evidence_level": "opened_text",
                    "visible_time_text": "2026-09-03",
                }
            ],
        ):
            result = browser._read_native_fact_candidate(candidate)
        self.assertTrue(result["success"])
        self.assertEqual(result["reader_type"], "bilibili_native_fact")
        self.assertIn("四禧丸子_Official", result["content"])

    def test_fact_pipeline_validates_native_candidate_without_web_search(self):
        candidate = {
            "title": "四禧丸子官方成员介绍",
            "description": "官方成员名单",
            "domain": "bilibili.com",
            "url": "https://www.bilibili.com/video/BV1nativefact",
            "native_platform": "bilibili",
            "native_visible_text": "四禧丸子官方成员介绍",
            "source_score": 100,
        }
        tools_stub = types.SimpleNamespace(
            score_sources=lambda _query, rows: rows,
            extract_answers=lambda _query, _rows: [
                {"answer": "成员为沐霂、又一、梨安、恬豆。"}
            ],
            _source_summary=lambda rows: rows,
        )
        with patch.dict(sys.modules, {"tools": tools_stub}), patch.object(
            browser,
            "_plan_fact_intent_scope",
            return_value={"scope_type": "CURRENT_ACTIVE_STATE"},
        ), patch.object(
            browser,
            "_plan_fact_entity_scope",
            return_value={"included_scope": "四禧丸子"},
        ), patch.object(
            browser,
            "_audit_fact_search_query",
            return_value={"approved_search_query": "四禧丸子 当前成员"},
        ), patch.object(
            browser,
            "_discover_native_fixed_fact_candidates",
            return_value={
                "status": "OK",
                "results": [candidate],
                "discovery_type": "site_native_fact",
            },
        ), patch.object(
            browser,
            "_read_native_fact_candidate",
            return_value={
                "success": True,
                "content": "UP主: 四禧丸子_Official\n简介: 官方成员名单",
                "reader_type": "bilibili_native_fact",
                "error": None,
            },
        ) as native_reader, patch.object(
            browser,
            "_validate_temporal_scope",
            return_value={"time_scope_match": True},
        ), patch.object(
            browser,
            "_validate_candidate_answer",
            return_value={"accepted": True, "reason": "official page"},
        ), patch.object(
            browser,
            "_try_search_summary_fact_answer",
            return_value=None,
        ), patch.object(
            browser,
            "discover_web",
            side_effect=AssertionError("native result must not use web search"),
        ):
            result = browser.fact_lookup_controller(
                "四禧丸子 当前成员",
                user_request="请去B站核实，只看官方账号",
                requested_sites=["bilibili.com"],
                official_only=True,
            )
        self.assertEqual(result["status"], "OK")
        self.assertIn("沐霂", result["direct_reply"])
        native_reader.assert_called_once()


class NativeFactPackagingTests(unittest.TestCase):
    def test_build_metadata_and_release_test_are_current(self):
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(metadata["package_id"], BUILD_ID)
        self.assertTrue(
            (ROOT / "TEST_BILIBILI_NATIVE_FACT_EXECUTOR_V1_10_51_3.ps1").exists()
        )


if __name__ == "__main__":
    unittest.main()
