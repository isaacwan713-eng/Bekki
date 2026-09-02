import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import unittest
from unittest.mock import patch

import magi
import melchior
import social_browser
import tools


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SocialBilibiliRedditV11028Tests(unittest.TestCase):
    def test_bilibili_search_url_preserves_source_query(self):
        query = "又一充电中 袁雨桢 BV1abc UID1660392980"
        parsed = urlparse(social_browser.social_search_url("bilibili", query))
        self.assertEqual(parsed.netloc, "search.bilibili.com")
        self.assertEqual(parsed.path, "/all")
        self.assertEqual(parse_qs(parsed.query)["keyword"], [query])

    def test_reddit_search_url_preserves_source_query(self):
        query = "microduck review r/robotics"
        parsed = urlparse(social_browser.social_search_url("reddit", query))
        self.assertEqual(parsed.netloc, "www.reddit.com")
        self.assertEqual(parsed.path, "/r/robotics/search/")
        self.assertEqual(parse_qs(parsed.query)["q"], ["microduck review"])
        self.assertEqual(parse_qs(parsed.query)["restrict_sr"], ["1"])
        self.assertEqual(parse_qs(parsed.query)["sort"], ["relevance"])

    def test_bilibili_only_accepts_bounded_public_content_urls(self):
        allowed = (
            "https://www.bilibili.com/video/BV1abc",
            "https://www.bilibili.com/opus/123456",
            "https://www.bilibili.com/read/cv123456",
            "https://space.bilibili.com/1660392980",
            "https://t.bilibili.com/123456",
            "https://live.bilibili.com/123456",
            "https://b23.tv/BV1abc",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    social_browser._allowed_social_url("bilibili", value),
                    value,
                )
        rejected = (
            "https://search.bilibili.com/all?keyword=x",
            "https://www.bilibili.com/",
            "https://space.bilibili.com/not-a-uid",
            "https://example.com/video/BV1abc",
        )
        for value in rejected:
            with self.subTest(value=value):
                self.assertEqual(
                    social_browser._allowed_social_url("bilibili", value),
                    "",
                )

    def test_reddit_only_accepts_post_permalinks(self):
        allowed = (
            "https://www.reddit.com/r/robotics/comments/abc123/example/",
            "https://old.reddit.com/r/robotics/comments/abc123/example/",
            "https://redd.it/abc123",
        )
        for value in allowed:
            with self.subTest(value=value):
                self.assertEqual(
                    social_browser._allowed_social_url("reddit", value),
                    value,
                )
        rejected = (
            "https://www.reddit.com/search/?q=microduck",
            "https://www.reddit.com/r/robotics/",
            "https://example.com/r/robotics/comments/abc123/example/",
        )
        for value in rejected:
            with self.subTest(value=value):
                self.assertEqual(
                    social_browser._allowed_social_url("reddit", value),
                    "",
                )

    def test_reddit_text_post_does_not_require_an_image(self):
        class FakePage:
            def evaluate(self, _script):
                return [{
                    "url": (
                        "https://www.reddit.com/r/robotics/comments/abc123/"
                        "microduck_review/"
                    ),
                    "visible_text": "Microduck review posted 2 hours ago",
                    "image_url": "",
                    "image_alt": "",
                }]

        candidates = social_browser._extract_post_candidates(
            FakePage(), "reddit"
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["image_url"], "")

    def test_visual_first_platform_still_rejects_text_only_navigation(self):
        class FakePage:
            def evaluate(self, _script):
                return [{
                    "url": "https://www.rednote.com/explore/abc",
                    "visible_text": "A text-only navigation-like item",
                    "image_url": "",
                    "image_alt": "",
                }]

        self.assertEqual(
            social_browser._extract_post_candidates(
                FakePage(), "xiaohongshu"
            ),
            [],
        )

    def test_social_query_ai_keeps_bilibili_and_reddit_terms_verbatim(self):
        cases = (
            (
                "去 Bilibili 搜索 又一充电中 袁雨桢 BV1abc UID1660392980",
                ["bilibili"],
                "又一充电中 袁雨桢 BV1abc UID1660392980",
            ),
            (
                "去 Reddit 搜索 microduck review r/robotics",
                ["reddit"],
                "microduck review r/robotics",
            ),
        )
        for message, platforms, expected in cases:
            with self.subTest(platforms=platforms), patch.object(
                tools, "run_ai_prompt", return_value={"query": expected}
            ):
                self.assertEqual(
                    tools.build_social_query(message, platforms), expected
                )

    def test_existing_magi_and_melchior_accept_new_social_platforms(self):
        for platform in ("bilibili", "reddit"):
            with self.subTest(platform=platform):
                route = {
                    "lane": "SEARCH",
                    "confidence": 0.99,
                    "reason": "The user explicitly requested platform posts.",
                    "social_scope": "SOCIAL_RESEARCH",
                    "social_platforms": [platform],
                    "search_scope": "SOCIAL_RESEARCH",
                    "recommendation_domain": None,
                    "local_knowledge_sufficiency": "NONE",
                }
                with patch.object(
                    magi.tools, "run_ai_prompt", return_value=route
                ), patch.object(magi.tools, "unload_model"):
                    result = magi.route_request("explicit platform search")
                self.assertEqual(result["social_platforms"], [platform])
                plan = melchior._authoritative_social_plan(result)
                self.assertEqual(plan["response_mode"], "SOCIAL_RESEARCH")
                self.assertEqual(plan["social_platforms"], [platform])

    def test_prompts_expose_new_platforms_without_translation(self):
        gate = (PROJECT_ROOT / "prompts" / "magi_gate.txt").read_text(
            encoding="utf-8"
        )
        query = (PROJECT_ROOT / "prompts" / "social_query.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn('["bilibili"]', gate)
        self.assertIn('["reddit"]', gate)
        self.assertIn("strict no-translation policy", query)
        self.assertIn("又一充电中 袁雨桢", query)
        self.assertIn("microduck review r/robotics", query)

    def test_root_and_casper_social_runtime_copies_match(self):
        pairs = (
            ("melchior.py", "casper/melchior.py"),
            ("social_browser.py", "casper/social_browser.py"),
            ("tools.py", "casper/tools.py"),
            ("prompts/melchior_router.txt", "casper/prompts/melchior_router.txt"),
            ("prompts/social_query.txt", "casper/prompts/social_query.txt"),
        )
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertEqual(
                    (PROJECT_ROOT / left).read_bytes(),
                    (PROJECT_ROOT / right).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
