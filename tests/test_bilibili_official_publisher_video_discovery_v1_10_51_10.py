from pathlib import Path
import json
import unittest
from unittest.mock import patch

import social_browser
from casper import browser


ROOT = Path(__file__).resolve().parents[1]
BUILD_ID = "bekki-knowledge-visual-recall-v1-10-54-7-20260910"


class BilibiliPublisherVideoRouteTests(unittest.TestCase):
    def setUp(self):
        self.identity = {
            "publisher_name": "四禧丸子_Official",
            "publisher_url": "https://space.bilibili.com/1129115529",
            "entity_expression": "四禧丸子",
            "official_identity_verified": True,
            "official_identity_basis": (
                "bilibili_upuser_exact_entity_and_official_marker"
            ),
        }

    def test_build_and_discovery_contract(self):
        self.assertIn(BUILD_ID, (ROOT / "main.py").read_text(encoding="utf-8"))
        metadata = json.loads(
            (ROOT / "BEKKI_BUILD.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["build_id"], BUILD_ID)
        self.assertEqual(
            metadata["update_kind"],
            "Knowledge Visual Recall V1.10.54.7",
        )
        self.assertEqual(
            metadata["parent_build"],
            "Knowledge Autonomous Visual Evidence V1.10.54.6",
        )
        self.assertEqual(
            browser.BILIBILI_OFFICIAL_PUBLISHER_VIDEO_DISCOVERY_VERSION,
            1,
        )
        release_test = ROOT / (
            "TEST_BILIBILI_OFFICIAL_PUBLISHER_VIDEO_DISCOVERY_"
            "V1_10_51_10.ps1"
        )
        self.assertTrue(release_test.is_file())
        self.assertTrue(all(value < 128 for value in release_test.read_bytes()))
        self.assertTrue(
            (
                ROOT
                / "BILIBILI_OFFICIAL_PUBLISHER_VIDEO_DISCOVERY_"
                "V1_10_51_10_NOTES.md"
            ).is_file()
        )

    def test_publisher_local_query_removes_identity_and_question_words(self):
        query = "四禧丸子_Official 官方账号 成员是谁"
        self.assertEqual(
            browser._bilibili_publisher_video_keyword(query, self.identity),
            "成员",
        )
        self.assertEqual(
            browser._bilibili_publisher_video_keyword(
                "四禧丸子 2022年1月15日公开资料中的四位成员",
                self.identity,
            ),
            "成员",
        )
        self.assertEqual(
            browser._bilibili_publisher_video_page_urls(
                self.identity, query
            ),
            [
                (
                    "https://space.bilibili.com/1129115529/"
                    "search/video?keyword=%E6%88%90%E5%91%98"
                ),
                (
                    "https://space.bilibili.com/1129115529/"
                    "upload/video"
                ),
            ],
        )

    def test_video_page_must_remain_under_the_proven_numeric_uid(self):
        expected = self.identity["publisher_url"]
        self.assertEqual(
            browser._canonical_bilibili_publisher_url(expected),
            expected,
        )
        self.assertEqual(
            browser._canonical_bilibili_publisher_url(
                "http://space.bilibili.com/1129115529"
            ),
            "",
        )
        self.assertTrue(
            browser._bilibili_publisher_video_page_is_bound(
                expected + "/search/video?keyword=x",
                expected,
            )
        )
        self.assertTrue(
            browser._bilibili_publisher_video_page_is_bound(
                expected + "/upload/video",
                expected,
            )
        )
        self.assertFalse(
            browser._bilibili_publisher_video_page_is_bound(
                "https://space.bilibili.com/999/upload/video",
                expected,
            )
        )
        self.assertFalse(
            browser._bilibili_publisher_video_page_is_bound(
                "https://evil.example/1129115529/upload/video",
                expected,
            )
        )
        self.assertFalse(
            browser._bilibili_publisher_video_page_is_bound(
                "https://space.bilibili.com:444/"
                "1129115529/upload/video",
                expected,
            )
        )
        self.assertFalse(
            browser._bilibili_publisher_video_page_is_bound(
                "https://space.bilibili.com:bad/"
                "1129115529/upload/video",
                expected,
            )
        )

    def test_publisher_page_discovery_binds_only_rendered_video_cards(self):
        opened = (
            "https://space.bilibili.com/1129115529/"
            "search/video?keyword=%E6%88%90%E5%91%98"
        )
        page = {
            "post_candidates": [
                {
                    "url": "https://www.bilibili.com/video/BV1official",
                    "visible_text": "四禧丸子成员介绍",
                    "source_kind": "result_card",
                    "dom_card_matched": True,
                },
                {
                    "url": "https://www.bilibili.com/video/BV1generic",
                    "visible_text": "只有链接，没有投稿卡片",
                    "source_kind": "generic_link",
                    "dom_card_matched": False,
                },
                {
                    "url": "https://space.bilibili.com/1129115529",
                    "visible_text": "账号首页",
                    "source_kind": "result_card",
                    "dom_card_matched": True,
                },
            ],
        }
        with patch.object(
            browser,
            "_open_bilibili_publisher_video_page",
            return_value=opened,
        ), patch.object(
            social_browser,
            "inspect_active_social_page",
            return_value=page,
        ) as inspected, patch.object(
            social_browser,
            "close_social_search",
        ) as closed, patch.object(
            browser.time,
            "sleep",
            return_value=None,
        ):
            result = browser._discover_bilibili_verified_publisher_videos(
                self.identity,
                "四禧丸子_Official 官方账号 成员是谁",
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["url"],
            "https://www.bilibili.com/video/BV1official",
        )
        self.assertEqual(
            result[0]["author_url"],
            self.identity["publisher_url"],
        )
        self.assertTrue(result[0]["official_publisher_page_bound"])
        self.assertEqual(
            result[0]["official_publisher_video_discovery_version"], 1
        )
        inspected.assert_called_once_with(
            "bilibili",
            expected_url=opened,
        )
        closed.assert_called_once_with(opened)

    def test_unverified_identity_cannot_open_a_publisher_page(self):
        identity = dict(
            self.identity,
            official_identity_verified=False,
        )
        with patch.object(
            browser,
            "_open_bilibili_publisher_video_page",
            side_effect=AssertionError("must not open"),
        ) as opened:
            result = browser._discover_bilibili_verified_publisher_videos(
                identity,
                "成员",
            )
        self.assertEqual(result, [])
        opened.assert_not_called()

    def test_native_official_lookup_prefers_verified_publisher_page(self):
        profile_url = "https://search.bilibili.com/upuser?keyword=x"
        profile_page = {
            "post_candidates": [{
                "url": self.identity["publisher_url"],
                "visible_text": "四禧丸子_Official 虚拟偶像团体",
                "source_kind": "profile_result",
                "profile_name": "四禧丸子_Official",
                "profile_result_matched": True,
                "profile_verified": True,
            }]
        }
        publisher_video = {
            "url": "https://www.bilibili.com/video/BV1official",
            "visible_text": "四禧丸子成员介绍",
            "source_kind": "result_card",
            "dom_card_matched": True,
            "author": "四禧丸子_Official",
            "author_url": self.identity["publisher_url"],
            "official_publisher_page_bound": True,
            "official_publisher_video_discovery_version": 1,
        }
        with patch.object(
            social_browser,
            "open_social_search",
            return_value={"url": profile_url},
        ) as opened, patch.object(
            social_browser,
            "inspect_active_social_page",
            return_value=profile_page,
        ), patch.object(
            social_browser,
            "close_social_search",
        ), patch.object(
            browser,
            "_discover_bilibili_verified_publisher_videos",
            return_value=[publisher_video],
        ) as publisher_discovery, patch.object(
            browser.time,
            "sleep",
            return_value=None,
        ):
            result = browser._discover_native_fixed_fact_candidates(
                "site:bilibili.com 四禧丸子_Official 官方账号 成员是谁",
                ["bilibili.com"],
                official_only=True,
                entity_name="四禧丸子",
            )

        self.assertEqual(result["status"], "OK")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(opened.call_count, 1)
        publisher_discovery.assert_called_once()
        self.assertTrue(
            result["results"][0]["official_publisher_page_bound"]
        )
        self.assertEqual(
            result["results"][0][
                "official_publisher_video_discovery_version"
            ],
            1,
        )


if __name__ == "__main__":
    unittest.main()
